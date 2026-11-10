"""Published CleanBench inference bridge; see baselines/provenance.json."""

from __future__ import annotations

import csv
import importlib.util
import random
from pathlib import Path

from baselines.common import fingerprint

from .native_correction import UPSTREAM

SOURCE = UPSTREAM / "Relative_Trust/relative.py"


def load_upstream():
    spec = importlib.util.spec_from_file_location("cleanbench_relative_trust", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.PERFECTED = False
    module.ONLYED = False
    return module


def execute(dirty: Path, rule_path: Path, seed: int, *, diagnostic_clean: Path | None = None):
    """Keep native constraint search, vertex cover, sampling and assignment unchanged."""
    import numpy as np

    with dirty.open(newline="", encoding="utf-8") as stream:
        header, *rows = csv.reader(stream)
    if not rows or len(set(header)) != len(header) or any(len(row) != len(header) for row in rows):
        raise ValueError(
            "Relative Trust requires a nonempty rectangular source with unique headers"
        )
    if not rule_path.read_text().strip():
        # The original ADR wrapper bypasses native inference when no unary FD
        # was discovered. Do not introduce parser-only changes in this branch.
        return {
            "changes": [],
            "labeled_rows": [],
            "new_native_inference_runs": 0,
            "abstention": "no unary FDs",
        }
    random.seed(seed)
    np.random.seed(seed)
    module = load_upstream()

    class Native(module.RelaTrust):
        def evaluation(self):
            # Only this metric/file-output method reads clean values after
            # construction. Shared campaign scorers own benchmark evaluation.
            return None

    cleaner = Native(str(dirty), str(diagnostic_clean or dirty), str(rule_path))
    if list(cleaner.schema) != header or len(cleaner.dirty_csv) != len(rows):
        raise ValueError("Native CSV reader changed source coordinates")
    native_before = cleaner.dirty_csv.values.tolist()
    cleaner.run()
    if list(cleaner.rep_csv.columns) != header or len(cleaner.rep_csv) != len(rows):
        raise ValueError("Native Relative Trust changed repaired-table coordinates")
    changes = []
    repair_changes = 0
    for i, row in enumerate(cleaner.rep_csv.values.tolist()):
        for j, value in enumerate(row):
            if not isinstance(value, str):
                raise ValueError("Native Relative Trust returned a non-string value")
            repair_changes += value != native_before[i][j]
            if value != rows[i][j]:
                changes.append({"row": i, "col": j, "corrected_value": value})
    return {
        "changes": changes,
        "labeled_rows": [],
        "new_native_inference_runs": 1,
        "native_parser_changed_cells": sum(
            value != rows[i][j]
            for i, row in enumerate(native_before)
            for j, value in enumerate(row)
        ),
        "native_repair_changed_cells": repair_changes,
        "native_input_sha256": fingerprint(native_before),
        "native_proposed_cells": [list(cell) for cell in sorted(set(cleaner.rep_cells))],
        "final_constraints": cleaner.cur_fd,
        "state_tree_nodes": cleaner.tree.node_num,
        "native_tau": cleaner.tau,
    }
