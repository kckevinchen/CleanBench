"""Published CleanBench inference bridge; see baselines/provenance.json."""

from __future__ import annotations

import collections
import importlib.util
from pathlib import Path

SOURCE = Path(__file__).resolve().parent / "external/rein/rein-benchmark/cleaners/katara/katara.py"


def native():
    spec = importlib.util.spec_from_file_location("katara_native", SOURCE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def infer(rows, projected):
    mod = native()
    types = set()
    candidates = collections.defaultdict(set)
    matched = set()
    if not rows:
        return {
            "detections": [],
            "changes": [],
            "unresolved_type_violations": [],
            "conflicting_suggestions": [],
            "matched_kb_files": [],
        }
    for item in projected:
        local = {}
        domain = set(item["types"])
        relations = item["relations"]
        for j in range(len(rows[0])):
            mod.domain_spec_col_type(rows, j, domain, local, 0.2, True)
        types.update(local)
        for relation, subjects in relations.items():
            for i in range(len(rows[0])):
                for j in range(i + 1, len(rows[0])):
                    proposals = {}
                    mod.domain_spec_colpair(rows, i, j, {relation: subjects}, proposals, 0.15, True)
                    for coordinate, value in proposals.items():
                        candidates[coordinate].add(value)
                    if proposals:
                        matched.add(item["file"])
    changes = [
        {"row": i, "col": j, "corrected_value": next(iter(values))}
        for (i, j), values in sorted(candidates.items())
        if len(values) == 1 and next(iter(values)) != rows[i][j]
    ]
    return {
        "detections": [{"row": i, "col": j} for i, j in sorted(types | set(candidates))],
        "changes": changes,
        "unresolved_type_violations": [list(c) for c in sorted(types - set(candidates))],
        "conflicting_suggestions": [
            {"row": i, "col": j, "values": sorted(v)}
            for (i, j), v in sorted(candidates.items())
            if len(v) > 1
        ],
        "matched_kb_files": sorted(matched),
        "candidate_cells": len(candidates),
    }
