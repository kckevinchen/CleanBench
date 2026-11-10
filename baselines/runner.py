"""Portable Table 3 inference entry point. Inputs contain dirty data only."""

from __future__ import annotations

import argparse
import csv
import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from baselines.common import (
    NATIVE_ROOT,
    ROOT,
    ConfigurationError,
    atomic_json,
    fingerprint,
    read_json,
    read_table,
    sha,
    validate_changes,
)

CONSTRAINTS = {
    "bigdansing",
    "holistic",
    "daisyp",
    "horizon",
    "relative_trust",
    "nadeef",
    "llunatic",
    "uniclean",
}
METHODS = CONSTRAINTS | {
    "symspell",
    "neuspell",
    "katara",
    "cleanagent",
    "cocoon",
    "gpt41",
    "gpt52",
    "gpt55",
    "astra",
    "codex",
    "copilot",
}


def constraint(method, dirty, work, dataset, repetition):
    header, rows = read_table(dirty)
    reference = read_json(ROOT / "config/constraint_rules.json")
    bank = reference["tables"]
    if dataset not in bank:
        raise ValueError("No fixed LLM rules for this table ID")
    if fingerprint(rows) != reference["input_rows_sha256"][dataset]:
        raise ValueError("Input strings differ from the fixed-rule table")
    rules = bank[dataset][method]
    # Positional aliases are the exact serializer used in the paper.
    alias = work / "positional.csv"
    with alias.open("w", newline="") as stream:
        csv.writer(stream, lineterminator="\n").writerows(
            [[f"C{i}" for i in range(len(header))], *rows]
        )
    request = {
        **rules,
        "method": method,
        "dirty_csv": str(alias),
        "work": str(work / "native"),
        "project": str(NATIVE_ROOT),
        "seed": 20261108 + repetition,
    }
    if method in {"llunatic", "uniclean"}:
        if not rules["fds"]:
            return {"changes": []}
        native_work = Path(request["work"])
        native_work.mkdir()
        if method == "llunatic":
            from baselines.native.external.llunatic.run import execute

            return execute(request, rows, native_work)
        from baselines.native.external.uniclean.run import execute

        return execute(request)
    from baselines.native.constraints.comparison_worker import execute

    return execute(request)


def workflows(method, dirty, work):
    from baselines.api import WorkflowChat

    chat = WorkflowChat(method, work)
    if method == "cocoon":
        import pandas as pd

        from baselines.native.external.cocoon.native import clean_table

        # Preserve the published native CSV parser.
        frame = pd.read_csv(dirty, dtype=str, keep_default_na=False, low_memory=False)
        result, details = clean_table(frame, chat)
        atomic_json(work / "workflow.json", details)
        _, rows = read_table(dirty)
        return {
            "changes": [
                dict(row=i, col=j, corrected_value=str(result.iat[i, j]))
                for i, r in enumerate(rows)
                for j, v in enumerate(r)
                if result.iat[i, j] != v
            ]
        }
    from baselines.native.external.cleanagent.repaired import execute

    recipe = dict(
        revision="cleanagent_runtime_repair_v1",
        model=chat.recipe["model"],
        prompt_file=str(ROOT / "prompts/cleanagent_repaired.yaml"),
        max_programmer_turns=6,
        execution_limits=dict(memory_limit_mb=4096, file_limit_mb=64, code_timeout_seconds=600),
    )
    return execute(dirty, work, recipe, chat=chat)


def katara(dirty, work, dataset):
    from baselines.native.katara import infer

    _, rows = read_table(dirty)
    projected = read_json(work.parents[1] / "kb_projection" / (dataset + ".json"))
    if projected is None:
        raise ValueError("Missing KATARA projection for this run")
    return infer(rows, projected)


def one(method, dirty, work, dataset, repetition):
    if method in CONSTRAINTS:
        return constraint(method, dirty, work, dataset, repetition)
    if method in {"cleanagent", "cocoon"}:
        return workflows(method, dirty, work)
    if method in {"gpt41", "gpt52", "gpt55", "astra"}:
        from baselines.api import direct

        return direct(method, dirty, work, repetition)
    if method in {"codex", "copilot"}:
        from baselines.coding import execute

        return execute(method, dirty, work)
    if method == "katara":
        return katara(dirty, work, dataset)
    raise ValueError("Unknown per-table method")


def spelling(method, inputs, entries):
    from baselines.native.external.typo_baselines.run_typo import (
        HAS_ALPHA,
        run_neuspell,
        run_symspell,
    )

    cells = []
    for ds in entries:
        _, rows = read_table(inputs / ds / "dirty.csv")
        cells.extend(
            ((ds, i, j), v)
            for i, r in enumerate(rows)
            for j, v in enumerate(r)
            if HAS_ALPHA.search(v)
        )
    args = SimpleNamespace(
        max_edit_distance=2,
        min_token_len=4,
        skip_allcaps=True,
        flag_unknown=False,
        neuspell_checker="BertChecker",
        neuspell_batch=256,
    )
    result = (run_symspell if method == "symspell" else run_neuspell)(cells, args)
    return [
        dict(dataset=ds, row=i, col=j, corrected_value=value)
        for (ds, i, j), value in result.items()
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--method", required=True, choices=sorted(METHODS))
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--execution", type=Path)
    parser.add_argument("--repetition", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument(
        "--limit", type=int, default=0, help="Smoke test only; excluded tables stay unknown"
    )
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        request = read_json(args.worker)
        result = one(
            args.method,
            Path(request["dirty"]),
            Path(request["work"]),
            request["dataset"],
            args.repetition,
        )
        headers, rows = read_table(request["dirty"])
        validate_changes(result["changes"], headers, rows)
        atomic_json(args.worker.with_name("result.json"), result)
        return
    if not all((args.inputs, args.predictions, args.execution)):
        parser.error("--inputs, --predictions and --execution are required")
    inputs = args.inputs.resolve()
    output = args.predictions.parent.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if args.predictions.exists() or args.execution.exists():
        parser.error("Use new output files for each independent run")
    entries = read_json(inputs / "_manifest.json")["datasets"]
    selected = sorted(entries)[: args.limit or None]
    for ds in selected:
        if sha(inputs / ds / "dirty.csv") != entries[ds]["dirty_sha256"]:
            raise ValueError("Dirty input checksum mismatch")
    executions = dict.fromkeys(entries, "unknown")
    predictions = []
    if args.method == "katara":
        from baselines.katara import prepare

        prepare(inputs, selected, output)
    if args.method in {"symspell", "neuspell"}:
        predictions = spelling(args.method, inputs, selected)
        executions.update(dict.fromkeys(selected, "complete"))
    else:
        for ds in selected:
            work = output / "tables" / ds
            work.mkdir(parents=True, exist_ok=False)
            request = work / "request.json"
            atomic_json(
                request, dict(dataset=ds, dirty=str(inputs / ds / "dirty.csv"), work=str(work))
            )
            command = [
                sys.executable,
                "-m",
                "baselines.runner",
                "--method",
                args.method,
                "--repetition",
                str(args.repetition),
                "--worker",
                str(request),
            ]
            code = None
            with (work / "worker.log").open("w") as log:
                process = subprocess.Popen(
                    command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
                )
                try:
                    deadline = (
                        900
                        if args.method == "cocoon"
                        else 330
                        if args.method in {"codex", "copilot"}
                        else 300
                    )
                    code = process.wait(timeout=deadline)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
            if code == 78:
                raise RuntimeError("Authentication or model configuration failed; see worker.log")
            result = read_json(work / "result.json")
            if code == 0 and result is not None:
                executions[ds] = "complete"
                predictions.extend(dict(dataset=ds, **p) for p in result["changes"])
            else:
                executions[ds] = "failed"
            atomic_json(work / "execution.json", dict(status=executions[ds], exit_code=code))
            atomic_json(args.execution, executions)
            print(f"{args.method}: {ds}: {executions[ds]}", flush=True)
    if not any(v == "complete" for v in executions.values()):
        raise RuntimeError("No table completed; inspect worker logs before launching another run")
    args.predictions.write_text(
        "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in predictions)
    )
    atomic_json(args.execution, executions)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        status = getattr(error, "status_code", None)
        if (
            isinstance(error, ConfigurationError)
            or status in {401, 403, 404}
            or getattr(error, "code", None) == "insufficient_quota"
        ):
            # Do not echo authentication error bodies or attempt all 1,000 tables.
            print(
                f"{type(error).__name__}: HTTP {status}; check runtime credentials/model",
                file=sys.stderr,
            )
            raise SystemExit(78) from None
        raise
