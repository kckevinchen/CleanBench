"""Published CleanBench inference bridge; see baselines/provenance.json."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from baselines.common import atomic_json, read_json


def prepare_java(method, header, rows, rules, work, settings):
    """Serialize supplied FDs using the existing native batch adapters' contracts."""
    work.mkdir(parents=True, exist_ok=False)
    if header != [f"C{i}" for i in range(len(header))]:
        raise ValueError("External bank requires positional column names")
    for rule in rules:
        lhs, rhs = rule["lhs"], rule["rhs"]
        if not lhs or any(c not in header for c in lhs + [rhs]) or rhs in lhs:
            raise ValueError("Invalid supplied FD")
    atomic_json(work / "supplied_rules.json", rules)
    if method == "nadeef":
        atomic_json(
            work / "input.json", {"rows": rows, "n_columns": len(header), "n_rules": len(rules)}
        )
        source = {
            "type": "derbymemory",
            "url": "memory:cleanbench;create=true",
            "username": "APP",
            "password": "APP",
        }
        native_rules = [
            {
                "name": f"FD{i}",
                "type": "fd",
                "table": ["INPUT_DATA"],
                "target": ["INPUT_DATA"],
                "value": [",".join(r["lhs"]) + "|" + r["rhs"]],
            }
            for i, r in enumerate(rules)
        ]
        atomic_json(work / "plan.json", {"source": source, "rule": native_rules})
        (work / "out").mkdir()
        (work / "nadeef.conf").write_text(
            "database.url=memory:cleanbench;create=true\ndatabase.type=derbymemory\ndatabase.username=APP\ndatabase.password=APP\ngeneral.outputPath=out\ngeneral.alwaysCompile=true\n"
            + f"general.maxIterationNumber={settings['nadeef_max_iterations']}\nruleext.fd=qa.qcri.nadeef.ruleext.FDRuleBuilder\n"
        )
    else:
        raise ValueError(method)


def execute(recipe):
    from baselines.native.external.adr.dc_correction import grid

    method = recipe["method"]
    dirty, work = Path(recipe["dirty_csv"]), Path(recipe["work"])
    header, rows = grid(dirty)
    rules, settings = recipe["rules"], recipe["settings"]
    if not rules and not recipe["lines"]:
        return {
            "changes": [],
            "detections": [],
            "abstention": "no supported constraints",
            "new_native_inference_runs": 0,
        }
    if method in {"bigdansing", "holistic"}:
        from .context_native import execute_native

        return execute_native(method, dirty, recipe["lines"], work)
    if method == "horizon":
        from baselines.native.external.adr.horizon_blind import execute as run

        return run(method, dirty, rules, work)
    if method == "relative_trust":
        import queue
        from types import SimpleNamespace

        from baselines.native.external.adr import relative_native

        work.mkdir(parents=True, exist_ok=False)
        path = work / "fds.txt"
        path.write_text("".join(f"{r['lhs'][0]} ⇒ {r['rhs']}\n" for r in rules))
        original_loader = relative_native.load_upstream

        class ObservedQueue(queue.PriorityQueue):
            def get(self, *args, **kwargs):
                if self.empty():
                    raise RuntimeError(
                        "Native Relative Trust search exhausted its queue and would block indefinitely"
                    )
                return super().get(*args, **kwargs)

        def observed_loader():
            native = original_loader()
            native.queue = SimpleNamespace(PriorityQueue=ObservedQueue)
            return native

        # The native search is single-threaded. Observe its documented empty
        # queue defect and fail promptly rather than waiting for a timeout.
        # This never manufactures a repair or changes successful queue results.
        relative_native.load_upstream = observed_loader
        try:
            result = relative_native.execute(dirty, path, recipe["seed"])
        finally:
            relative_native.load_upstream = original_loader
        return {**result, "detection_available": False}
    if method == "daisyp":
        from baselines.native.external.adr.daisy_native import execute as detect
        from baselines.native.external.adr.daisy_point import point_inference

        detection = detect(dirty, rules, work)
        atomic_json(work / "completed_detection.json", detection)
        result = point_inference(work)
        if result["nonliteral_selections"]:
            atomic_json(work / "invalid_point_output.json", result)
            raise ValueError("DaisyP returned range-valued/nonliteral selections")
        # Only native assignments are exported; parser-only differences excluded.
        result["changes"] = [
            c for c in result["changes"] if c["corrected_value"] != rows[c["row"]][c["col"]]
        ]
        return {**result, "detections": [{"row": i, "col": j} for i, j in detection["cells"]]}
    prepare_java(method, header, rows, rules, work, settings)
    if method == "nadeef":
        from baselines.native.external.nadeef.native import ROOT, predictions

        command = [
            str(ROOT / "mamba_env/bin/java"),
            "-Dfile.encoding=UTF-8",
            "-Xmx2g",
            "-cp",
            f"{ROOT}/build/bin/*:{ROOT}/build/adapter",
            "NadeefBatch",
            "input.json",
            "nadeef.conf",
            "plan.json",
            "native.json",
        ]
        with (work / "native.log").open("w") as log:
            subprocess.run(
                command,
                cwd=work,
                env={**os.environ, "TZ": "UTC", "JAVA_HOME": str(ROOT / "mamba_env")},
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=settings["native_timeout_seconds"],
                check=True,
            )
        result = read_json(work / "native.json")
        output = predictions(result, rows, "", "")
        return {
            "changes": [
                {k: v for k, v in p.items() if k not in {"dataset", "detector"}}
                for p in output["e2e"]
            ],
            "detections": [{"row": p["row"], "col": p["col"]} for p in output["detection"]],
            "iterations": result["iterations"],
            "converged": result["converged"],
        }
    raise ValueError(method)
