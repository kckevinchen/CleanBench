"""Execute method commands on fresh inputs, score their outputs, and compare Table 3."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.reproducibility.table3 import (  # noqa: E402
    compare,
    metrics,
    read,
    records,
    score_run,
    sha,
    summarize,
    verify,
    write_csv,
)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def prepare_inputs(reference, archive_path, output):
    """Materialize dirty strings and a source-coordinate index for method runners."""
    with zipfile.ZipFile(archive_path) as archive:
        row_map = {}
        for name in archive.namelist():
            if Path(name).name == "_ROW_MAP.json":
                mapping = json.loads(archive.read(name))
                row_map.update(
                    {r["source"]: r["exported_to_source"] for r in mapping.get("sources", [])}
                )
        entries = {}
        for dataset, table in reference["tables"].items():
            names = [n for n in archive.namelist() if n.endswith("/" + table["source"])]
            if len(names) != 1:
                raise ValueError(f"Cannot uniquely locate dirty source: {dataset}")
            grid = list(csv.reader(io.StringIO(archive.read(names[0]).decode("utf-8-sig"))))
            headers, rows = grid[0], grid[1:]
            source_rows = row_map.get(table["source"], list(range(len(rows))))
            inverse = {original: exported for exported, original in enumerate(source_rows)}
            columns = [headers.index(h) for h in table["headers"]]
            chosen = [[rows[inverse[i]][j] for j in columns] for i in table["original_rows"]]
            if len(chosen) != table["rows"]:
                raise ValueError("Dirty source row count differs")
            target = output / dataset / "dirty.csv"
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("w", newline="", encoding="utf-8") as stream:
                csv.writer(stream, lineterminator="\n").writerows([table["headers"], *chosen])
            entries[dataset] = {
                "n_rows": table["rows"],
                "n_cols": table["columns"],
                "source": table["source"],
                "source_path": names[0],
                "dirty_sha256": sha(target),
            }
    write(output / "_manifest.json", {"datasets": entries})


def validate_plan(plan, manifest, methods=None):
    if plan.get("schema_version") != 1:
        raise ValueError("Expected command-plan schema_version=1")
    known = {r["method"] for r in manifest["methods"]}
    selected = set(methods or known)
    if not selected <= known:
        raise ValueError("Requested method is absent from Table 3")
    if not selected <= plan["methods"].keys():
        raise ValueError(
            "Missing method commands: " + ", ".join(sorted(selected - plan["methods"].keys()))
        )
    for method in selected:
        command = plan["methods"][method].get("command")
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(arg, str) for arg in command)
        ):
            raise ValueError(f"Method command must be an argv list: {method}")
        text = " ".join(command)
        if not all("{" + key + "}" in text for key in ("inputs", "predictions", "execution")):
            raise ValueError(
                f"Command must declare inputs, predictions and execution paths: {method}"
            )
    return [run for run in manifest["runs"] if run["method"] in selected]


def run_plan(plan, manifest, reference, output, inputs, methods=None, dry_run=False):
    runs = validate_plan(plan, manifest, methods)
    observations, tasks, totals = {}, [], []
    for run in runs:
        spec = plan["methods"][run["method"]]
        directory = output / "methods" / run["identity"]
        values = {
            "python": sys.executable,
            "repo": str(ROOT),
            "inputs": str(inputs),
            "run_dir": str(directory),
            "predictions": str(directory / "predictions.jsonl"),
            "execution": str(directory / "execution.json"),
            "method": run["method"],
            "run": str(run["run"]),
        }
        command = [arg.format_map(values) for arg in spec["command"]]
        tasks.append({"method": run["method"], "run": run["run"], "command": command})
        if dry_run:
            continue
        receipt = directory / "run_receipt.json"
        if receipt.exists():
            raise ValueError(
                f"Run directory already contains a trial: {directory}; use a new output directory"
            )
        directory.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        write(receipt, {"status": "running", "command": command})
        cwd = Path(spec.get("cwd", str(ROOT)).format_map(values)).resolve()
        with (directory / "inference.log").open("w") as log:
            result = subprocess.run(
                command,
                cwd=cwd,
                env={**os.environ, **spec.get("environment", {})},
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            )
        result_record = {
            "status": "complete" if result.returncode == 0 else "failed",
            "command": command,
            "exit_code": result.returncode,
            "elapsed_seconds": time.monotonic() - started,
        }
        write(receipt, result_record)
        if result.returncode:
            raise RuntimeError(
                f"Method exited {result.returncode}: {run['identity']}; see inference.log"
            )
        executions = read(Path(values["execution"]))
        counts = score_run(records(Path(values["predictions"])), reference, executions)
        values_scored, counts_scored = metrics(counts)
        observations[run["identity"]] = values_scored
        write(directory / "table_counts.json", counts)
        write(directory / "score.json", {**counts_scored, **values_scored})
        totals.append(
            {"method": run["method"], "run": run["run"], **counts_scored, **values_scored}
        )
        print(f"{run['method']} run {run['run']}: F1={values_scored['f1']:.4f}", flush=True)
    if dry_run:
        return {"tasks": tasks}
    selected = {r["method"] for r in runs}
    subset = {
        **manifest,
        "methods": [m for m in manifest["methods"] if m["method"] in selected],
        "runs": runs,
    }
    summaries = {view: summarize(subset, observations, view) for view in ("point", "variability")}
    for view, rows in summaries.items():
        write_csv(output / f"table3_{view}.csv", rows)
    write_csv(output / "per_run.csv", totals)
    return {"tasks": tasks, "summaries": summaries}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plan", type=Path, required=True, help="JSON argv commands, keyed by Table 3 method name"
    )
    parser.add_argument("--artifacts", type=Path, default=ROOT / "reproducibility/table3")
    parser.add_argument("--sources", type=Path, default=ROOT / "benchmark/sanitized_sources.zip")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/table3_fresh")
    parser.add_argument(
        "--method", action="append", help="Select a method; repeat to select several"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print commands without launching methods"
    )
    args = parser.parse_args()
    manifest = verify(args.artifacts.resolve())
    reference = read(args.artifacts / "reference.json")
    plan = read(args.plan)
    validate_plan(plan, manifest, args.method)
    output = args.output.resolve()
    inputs = output / "inputs"
    if not args.dry_run:
        if output.exists() and any(output.iterdir()):
            parser.error("Use a new, empty output directory for an independent experiment")
        prepare_inputs(reference, args.sources, inputs)
    result = run_plan(plan, manifest, reference, output, inputs, args.method, args.dry_run)
    if args.dry_run:
        print(json.dumps(result, indent=2))
        return
    differences = {}
    for view, rows in result["summaries"].items():
        # For a selected subset, retain the same expected method ordering.
        with (args.artifacts / f"expected/table3_{view}.csv").open(newline="") as stream:
            frozen = [
                r for r in csv.DictReader(stream) if r["method"] in {row["method"] for row in rows}
            ]
        expected = output / f"expected_{view}.csv"
        write_csv(expected, frozen)
        differences[view] = compare(rows, expected)
    write(output / "comparison.json", differences)
    print(f"Finished {len(result['tasks'])} fresh runs. Results: {output}")


if __name__ == "__main__":
    main()
