"""Evaluate predictions against this CleanBench benchmark directory.

This scorer supports two tasks:

* ``detection``: whether each erroneous cell is flagged.
* ``end_to_end``: whether each erroneous cell is flagged *and* corrected.

Benchmark contract:

* gold positives are ``benchmark_cell.json`` records with ``status="error"``;
* ``status="ambiguous"`` records are FP-immune;
* ``ignored.jsonl`` scopes are FP/FN-immune.

Input predictions can be JSONL or CSV and must identify cell keys
(``dataset, source, row, column``). For ``end_to_end`` task, predictions must
also provide corrected values (``corrected_value`` by default).

Examples::

    python benchmark/CleanBench/eval_cleanbench.py \
        --predictions /path/to/predictions.jsonl

    python benchmark/CleanBench/eval_cleanbench.py \
        --predictions /path/to/predictions.csv \
        --format csv \
        --default-dataset bing21_500 \
        --task end_to_end \
        --corrected-col corrected_value

If predictions were produced from ``sanitized_sources`` row indices, enable
``--use-row-map`` to map exported rows back to original benchmark rows.
"""

from __future__ import annotations

import argparse
import csv
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

CellKey = tuple[str, str, int, str]
BENCHMARK_DEFAULT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class IgnoreIndex:
    csv_scopes: set[tuple[str, str]]
    row_scopes: set[tuple[str, str, int]]
    col_scopes: set[tuple[str, str, str]]
    cell_scopes: set[CellKey] = field(default_factory=set)

    def contains(self, key: CellKey) -> bool:
        dataset, source, row, column = key
        return (
            (dataset, source) in self.csv_scopes
            or (dataset, source, row) in self.row_scopes
            or (dataset, source, column) in self.col_scopes
            or key in self.cell_scopes
        )


def _load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _load_ignore_index(path: Path) -> IgnoreIndex:
    csv_scopes: set[tuple[str, str]] = set()
    row_scopes: set[tuple[str, str, int]] = set()
    col_scopes: set[tuple[str, str, str]] = set()
    for rec in _load_jsonl(path):
        dataset = str(rec.get("dataset") or "")
        source = str(rec.get("source") or "")
        scope = str(rec.get("scope") or "")
        if not dataset or not source:
            continue
        if scope == "csv":
            csv_scopes.add((dataset, source))
        elif scope == "rows":
            row = rec.get("row")
            if isinstance(row, int):
                row_scopes.add((dataset, source, row))
        elif scope == "columns":
            col = rec.get("column")
            if isinstance(col, str) and col:
                col_scopes.add((dataset, source, col))
    # Explicit exclusions are authoritative. Keep the legacy per-cell skip
    # records as well; row-level skips (column="") do not mask cell labels.
    cells: set[CellKey] = set()
    neutral = path.parent / "neutral_cells.jsonl"
    if neutral.exists():
        pools: dict[str, str] = {}
        gold = path.parent / "benchmark_cell.json"
        for rec in _load_jsonl(gold):
            pools[rec["source"]] = rec["dataset"]
        corpus = path.parent / "sanitized_sources.zip"
        if corpus.exists():
            with zipfile.ZipFile(corpus) as archive:
                for name in archive.namelist():
                    parts = Path(name).parts
                    if len(parts) == 2 and name.endswith(".csv"):
                        pools[parts[1]] = parts[0]
        for rec in _load_jsonl(neutral):
            source, row, column = (rec.get(k) for k in ("source", "row", "column"))
            if rec.get("kind") == "skip" and column and type(row) is int and source in pools:
                cells.add((pools[source], source, row, column))
    return IgnoreIndex(
        csv_scopes=csv_scopes, row_scopes=row_scopes, col_scopes=col_scopes, cell_scopes=cells
    )


def _load_row_map(path: Path) -> dict[str, list[int]]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    mapping: dict[str, list[int]] = {}
    for item in obj.get("sources", []):
        source = item.get("source")
        exported_to_source = item.get("exported_to_source")
        if isinstance(source, str) and isinstance(exported_to_source, list):
            mapped_rows: list[int] = []
            ok = True
            for val in exported_to_source:
                if not isinstance(val, int):
                    ok = False
                    break
                mapped_rows.append(val)
            if ok:
                mapping[source] = mapped_rows
    return mapping


def _iter_prediction_rows(path: Path, fmt: str) -> Iterable[dict]:
    if fmt == "jsonl":
        yield from _load_jsonl(path)
        return
    if fmt == "csv":
        with path.open(encoding="utf-8", newline="") as fh:
            yield from csv.DictReader(fh)
        return
    raise ValueError(f"unsupported format: {fmt}")


def _resolve_format(path: Path, fmt: str) -> str:
    if fmt != "auto":
        return fmt
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return "csv"
    return "jsonl"


def _precision_recall_f1(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return precision, recall, f1


def _parse_correction(raw: object) -> object:
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)):
        return list(raw)
    if isinstance(raw, (dict, int, float, bool)):
        return raw
    text = str(raw).strip()
    if not text or text.lower() in {"null", "none", "nan"}:
        return None
    if text[0] in "[{\"'":
        try:
            return json.loads(text)
        except Exception:  # noqa: BLE001 - treat as literal string
            pass
    return text


def _norm_scalar(raw: object) -> str | None:
    parsed = _parse_correction(raw)
    if parsed is None:
        return None
    if isinstance(parsed, str):
        out = parsed.strip()
        return out if out else None
    if isinstance(parsed, bool):
        return "true" if parsed else "false"
    if isinstance(parsed, (int, float)):
        return str(parsed)
    return json.dumps(parsed, ensure_ascii=False, sort_keys=True)


def _norm_list(raw: object) -> set[str]:
    parsed = _parse_correction(raw)
    if isinstance(parsed, list):
        out = {_norm_scalar(v) for v in parsed}
        return {v for v in out if v is not None}
    scalar = _norm_scalar(parsed)
    return {scalar} if scalar is not None else set()


def _correction_matches(predicted: object, gold: object) -> bool:
    gold_parsed = _parse_correction(gold)
    pred_parsed = _parse_correction(predicted)

    if isinstance(gold_parsed, list):
        gold_set = _norm_list(gold_parsed)
        if not gold_set:
            return False
        pred_set = _norm_list(pred_parsed)
        return bool(pred_set & gold_set)

    gold_scalar = _norm_scalar(gold_parsed)
    if gold_scalar is None:
        return _norm_scalar(pred_parsed) is None
    pred_set = _norm_list(pred_parsed)
    return gold_scalar in pred_set


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", required=True, help="Path to prediction JSONL or CSV")
    parser.add_argument(
        "--benchmark-dir",
        default=str(BENCHMARK_DEFAULT),
        help="CleanBench directory (default: script directory)",
    )
    parser.add_argument(
        "--format",
        choices=("auto", "jsonl", "csv"),
        default="auto",
        help="Prediction file format (default: infer from extension)",
    )
    parser.add_argument(
        "--task",
        choices=("detection", "end_to_end"),
        default="detection",
        help="Scoring task: detection only, or detection plus correction match",
    )
    parser.add_argument("--dataset-col", default="dataset", help="Dataset field name")
    parser.add_argument("--source-col", default="source", help="Source field name")
    parser.add_argument("--row-col", default="row", help="Row index field name")
    parser.add_argument("--column-col", default="column", help="Column field name")
    parser.add_argument(
        "--corrected-col",
        default="corrected_value",
        help="Prediction corrected-value field name (used for --task end_to_end)",
    )
    parser.add_argument(
        "--default-dataset",
        default=None,
        help="Fallback dataset when the dataset field is missing/empty",
    )
    parser.add_argument(
        "--use-row-map",
        action="store_true",
        help="Map prediction row indices using <benchmark-dir>/sanitized_sources/_ROW_MAP.json",
    )
    parser.add_argument(
        "--details-csv",
        default=None,
        help="Optional path to write per-prediction classification details",
    )
    args = parser.parse_args()

    bench_dir = Path(args.benchmark_dir)
    preds_path = Path(args.predictions)
    fmt = _resolve_format(preds_path, args.format)

    gold_rows = _load_jsonl(bench_dir / "benchmark_cell.json")
    ignore_index = _load_ignore_index(bench_dir / "ignored.jsonl")
    row_map: dict[str, list[int]] = {}
    if args.use_row_map:
        row_map_path = bench_dir / "sanitized_sources" / "_ROW_MAP.json"
        if not row_map_path.exists():
            raise SystemExit(f"row-map requested but not found: {row_map_path}")
        row_map = _load_row_map(row_map_path)

    positive: set[CellKey] = set()
    gold_corrections: dict[CellKey, object] = {}
    ambiguous: set[CellKey] = set()
    for rec in gold_rows:
        key = (
            str(rec["dataset"]),
            str(rec["source"]),
            int(rec["row"]),
            str(rec["column"]),
        )
        status = str(rec.get("status") or "")
        if status == "error":
            positive.add(key)
            gold_corrections[key] = rec.get("corrected_value")
        elif status == "ambiguous":
            ambiguous.add(key)

    predicted: set[CellKey] = set()
    predicted_corrections: dict[CellKey, object] = {}
    duplicate_predictions = 0
    dropped_rows = 0
    invalid_rows = 0

    for rec in _iter_prediction_rows(preds_path, fmt):
        dataset = rec.get(args.dataset_col)
        source = rec.get(args.source_col)
        row = rec.get(args.row_col)
        column = rec.get(args.column_col)

        dataset_str = str(dataset).strip() if dataset is not None else ""
        if not dataset_str and args.default_dataset:
            dataset_str = args.default_dataset
        source_str = str(source).strip() if source is not None else ""
        col_str = str(column).strip() if column is not None else ""
        if not dataset_str or not source_str or not col_str:
            invalid_rows += 1
            continue

        try:
            row_int = int(row)
        except (TypeError, ValueError):
            invalid_rows += 1
            continue
        if row_int < 0:
            invalid_rows += 1
            continue

        if source_str in row_map:
            mapped = row_map[source_str]
            if row_int >= len(mapped):
                dropped_rows += 1
                continue
            row_int = mapped[row_int]

        key = (dataset_str, source_str, row_int, col_str)
        before = len(predicted)
        predicted.add(key)
        predicted_corrections[key] = rec.get(args.corrected_col)
        if len(predicted) == before:
            duplicate_predictions += 1

    tp_keys: set[CellKey] = set()
    fp_keys: set[CellKey] = set()
    ambiguous_immune_pred: set[CellKey] = set()
    ignored_immune_pred: set[CellKey] = set()
    wrong_correction_keys: set[CellKey] = set()

    for key in predicted:
        if key in ambiguous:
            ambiguous_immune_pred.add(key)
            continue
        if ignore_index.contains(key):
            ignored_immune_pred.add(key)
            continue
        if key not in positive:
            fp_keys.add(key)
            continue
        if args.task == "detection":
            tp_keys.add(key)
            continue
        pred_corr = predicted_corrections.get(key)
        gold_corr = gold_corrections.get(key)
        if _correction_matches(pred_corr, gold_corr):
            tp_keys.add(key)
        else:
            fp_keys.add(key)
            wrong_correction_keys.add(key)

    ignored_immune_gold = {k for k in positive if ignore_index.contains(k)}
    fn_keys = positive - tp_keys - ignored_immune_gold

    tp = len(tp_keys)
    fp = len(fp_keys)
    fn = len(fn_keys)
    precision, recall, f1 = _precision_recall_f1(tp, fp, fn)

    if args.details_csv:
        detail_path = Path(args.details_csv)
        detail_path.parent.mkdir(parents=True, exist_ok=True)
        with detail_path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["kind", "dataset", "source", "row", "column", "classification"])
            for key in sorted(tp_keys):
                writer.writerow(["prediction", *key, "tp"])
            for key in sorted(fp_keys):
                label = "fp_wrong_correction" if key in wrong_correction_keys else "fp"
                writer.writerow(["prediction", *key, label])
            for key in sorted(ambiguous_immune_pred):
                writer.writerow(["prediction", *key, "immune_ambiguous"])
            for key in sorted(ignored_immune_pred):
                writer.writerow(["prediction", *key, "immune_ignored"])
            for key in sorted(fn_keys):
                writer.writerow(["gold_error", *key, "fn"])

    print("=== CleanBench evaluation ===")
    print(f"task                     : {args.task}")
    print(f"benchmark_dir            : {bench_dir}")
    print(f"predictions              : {preds_path} ({fmt})")
    print(f"gold_error_cells         : {len(positive)}")
    print(f"gold_ambiguous_cells     : {len(ambiguous)}")
    print(f"predicted_cells_unique   : {len(predicted)}")
    print(f"predicted_duplicates     : {duplicate_predictions}")
    print(f"prediction_rows_invalid  : {invalid_rows}")
    if args.use_row_map:
        print(f"prediction_rows_dropped  : {dropped_rows} (row-map out-of-range)")
    print()
    print(f"TP: {tp}")
    print(f"FP: {fp}")
    print(f"FN: {fn}")
    print(f"immune_pred_ambiguous    : {len(ambiguous_immune_pred)}")
    print(f"immune_pred_ignored      : {len(ignored_immune_pred)}")
    print(f"immune_gold_ignored      : {len(ignored_immune_gold)}")
    if args.task == "end_to_end":
        print(f"fp_wrong_correction      : {len(wrong_correction_keys)}")
    print(f"precision: {precision:.6f}")
    print(f"recall   : {recall:.6f}")
    print(f"f1       : {f1:.6f}")
    if args.details_csv:
        print(f"details_csv: {args.details_csv}")


if __name__ == "__main__":
    main()
