"""Portable, standard-library-only scoring for the frozen Table 3 experiment."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

METRICS = (
    "precision",
    "recall",
    "f1",
    "fpr",
    "recall_typo-spelling",
    "recall_typo-formatting",
    "recall_inconsistency",
)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def records(path):
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inside(root, relative):
    path = (root / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(root.resolve()):
        raise ValueError(f"Artifact path must stay inside its bundle: {relative}")
    return path


def verify(root):
    manifest = read(root / "manifest.json")
    if manifest.get("schema_version") != 1:
        raise ValueError("Unsupported Table 3 artifact schema")
    for relative, expected in manifest["sha256"].items():
        if sha(inside(root, relative)) != expected:
            raise ValueError(f"Artifact checksum mismatch: {relative}")
    required = {"reference.json", "expected/table3_point.csv", "expected/table3_variability.csv"}
    for run in manifest["runs"]:
        required.update(run[k] for k in ("predictions", "counts", "metadata"))
    if not required <= manifest["sha256"].keys():
        raise ValueError("Manifest omits required artifact checksums")
    return manifest


def score_run(predictions, reference, executions):
    """Rescore literal replacements; target types are coordinate unions."""
    tables = reference["tables"]
    if set(executions) != set(tables):
        raise ValueError("Run does not declare execution for every benchmark table")
    targets = {(r["dataset"], r["row"], r["col"]): set(r["accepted"]) for r in reference["targets"]}
    immune = {tuple(c) for c in reference["immune"]}
    types = {k: {tuple(c) for c in cells} for k, cells in reference["types"].items()}
    hits, attempts, seen = set(), set(), set()
    for row in predictions:
        dataset, i, j = row["dataset"], row["row"], row["col"]
        if dataset not in tables or type(i) is not int or type(j) is not int:
            raise ValueError("Invalid prediction identity")
        table = tables[dataset]
        if not (0 <= i < table["rows"] and 0 <= j < table["columns"]):
            raise ValueError("Prediction coordinate outside its table")
        cell = dataset, i, j
        if cell in seen:
            raise ValueError("Duplicate prediction coordinate")
        seen.add(cell)
        value = row.get("corrected_value")
        if cell in immune or not isinstance(value, str):
            continue
        attempts.add(cell)
        if cell in targets and value in targets[cell]:
            hits.add(cell)
    per_table = {}
    local_targets, local_attempts, local_hits = defaultdict(set), defaultdict(set), defaultdict(set)
    for cell in targets:
        local_targets[cell[0]].add(cell)
    for cell in attempts:
        local_attempts[cell[0]].add(cell)
    for cell in hits:
        local_hits[cell[0]].add(cell)
    for dataset, table in tables.items():
        status = executions[dataset]
        if status not in {"complete", "failed", "unknown"}:
            raise ValueError("Invalid execution state")
        local = local_targets[dataset]
        correct = local_hits[dataset]
        attempted = local_attempts[dataset]
        per_table[dataset] = {
            "tp": len(correct),
            "fp": len(attempted - correct),
            "fn": len(local - correct),
            "fp_clean": len(attempted - targets.keys()),
            "clean_cells": table["clean_cells"],
            "execution": status,
            "types": {
                kind: {"hit": len(correct & cells), "gt": len(local & cells)}
                for kind, cells in types.items()
            },
        }
    return per_table


def metrics(counts):
    total = {
        k: sum(r[k] for r in counts.values()) for k in ("tp", "fp", "fn", "fp_clean", "clean_cells")
    }
    for row in counts.values():
        if any(type(row[k]) is not int or row[k] < 0 for k in total):
            raise ValueError("Invalid per-table count")
        if row["fp_clean"] > row["fp"] or row["fp_clean"] > row["clean_cells"]:
            raise ValueError("Invalid clean-cell false positive partition")
    tp, fp, fn = (total[k] for k in ("tp", "fp", "fn"))
    ratio = lambda a, b: 100 * a / b if b else 0.0
    result = {
        "precision": ratio(tp, tp + fp),
        "recall": ratio(tp, tp + fn),
        "f1": ratio(2 * tp, 2 * tp + fp + fn),
        "fpr": ratio(total["fp_clean"], total["clean_cells"]),
    }
    for kind in ("typo-spelling", "typo-formatting", "inconsistency"):
        result[f"recall_{kind}"] = ratio(
            sum(r["types"][kind]["hit"] for r in counts.values()),
            sum(r["types"][kind]["gt"] for r in counts.values()),
        )
    return result, {**total, "tables": len(counts), "targets": tp + fn}


def summarize(manifest, observations, view):
    rows = []
    for method in manifest["methods"]:
        runs = [
            r
            for r in manifest["runs"]
            if r["method"] == method["method"] and (view == "variability" or r["point_view"])
        ]
        if not runs:
            raise ValueError(f"Missing runs for {method['method']}")
        row = {
            "task": "e2e",
            "category": method["category"],
            "method": method["method"],
            "repetitions": len(runs),
        }
        for metric in METRICS:
            values = [observations[r["identity"]][metric] for r in runs]
            row[metric] = statistics.mean(values)
            if view == "variability":
                row[f"sd_{metric}"] = statistics.stdev(values) if len(values) > 1 else None
        rows.append(row)
    return rows


def compare(actual, expected):
    with expected.open(encoding="utf-8", newline="") as stream:
        frozen = list(csv.DictReader(stream))
    if [r["method"] for r in actual] != [r["method"] for r in frozen]:
        raise ValueError("Table 3 method roster/order differs")
    differences = []
    for row, gold in zip(actual, frozen):
        for key in ("repetitions", *METRICS, *(f"sd_{m}" for m in METRICS if f"sd_{m}" in row)):
            value = row[key]
            target = gold.get(key)
            if value is None and target in ("", None):
                continue
            if (
                target in ("", None)
                or value is None
                or not math.isclose(float(value), float(target), rel_tol=1e-10, abs_tol=1e-10)
            ):
                differences.append(
                    {"method": row["method"], "metric": key, "actual": value, "expected": target}
                )
    return differences


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def reproduce(root, out, counts_only=False):
    manifest = verify(root)
    reference = read(root / "reference.json")
    observed, scores = {}, []
    identities = set()
    for run in manifest["runs"]:
        if run["identity"] in identities:
            raise ValueError("A run identity was counted twice")
        identities.add(run["identity"])
        ledger = list(records(inside(root, run["counts"])))
        saved = {r["dataset"]: {k: v for k, v in r.items() if k != "dataset"} for r in ledger}
        if len(saved) != len(ledger) or set(saved) != set(reference["tables"]):
            raise ValueError("Incomplete per-table ledger")
        metadata = read(inside(root, run["metadata"]))
        if counts_only:
            tables = saved
        else:
            tables = score_run(
                records(inside(root, run["predictions"])), reference, metadata["execution"]
            )
            if tables != saved:
                raise ValueError(
                    f"Rescored predictions differ from saved counts: {run['identity']}"
                )
        values, totals = metrics(tables)
        if (
            totals["tables"] != reference["population"]["tables"]
            or totals["targets"] != reference["population"]["targets"]
            or totals["clean_cells"] != reference["population"]["clean_cells"]
        ):
            raise ValueError("Run differs from Table 3 population")
        observed[run["identity"]] = values
        scores.append({"method": run["method"], "run": run["run"], **totals, **values})
    out.mkdir(parents=True, exist_ok=True)
    differences = []
    for view in ("point", "variability"):
        rows = summarize(manifest, observed, view)
        write_csv(out / f"table3_{view}.csv", rows)
        differences.extend(compare(rows, root / f"expected/table3_{view}.csv"))
    write_csv(out / "per_run.csv", scores)
    result = {
        "matched": not differences,
        "methods": len(manifest["methods"]),
        "runs": len(scores),
        "mode": "counts" if counts_only else "predictions",
        "differences": differences,
    }
    (out / "verification.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
