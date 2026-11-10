"""Published CleanBench inference bridge; see baselines/provenance.json."""

from __future__ import annotations

import contextlib
import csv
import inspect
import io


def execute_native(method, dirty, lines, work):
    from baselines.native.external.adr.dc_correction import CLASSES, grid, load_upstream

    header, rows = grid(dirty)
    if not lines:
        return {
            "changes": [],
            "detections": [],
            "native_proposals": [],
            "abstention": "no supported accepted rules",
            "new_native_inference_runs": 0,
        }
    work.mkdir(parents=True, exist_ok=False)
    rule_file = work / "constraints.txt"
    rule_file.write_text("\n".join(lines) + ("\n" if method == "holistic" else ""))
    native = load_upstream(method)
    native.PERFECTED, native.ONLYED = False, False
    native.dirty_path = native.clean_path = str(dirty)
    for line in lines:
        parsed = native.DCRule(line, header)
        if parsed.variable != ["t1", "t2"]:
            raise ValueError("Native tuple interpretation changed")
        for p in parsed.predicates:
            if (
                p.opt not in {"=", "!="}
                or p.tuples != ["t1", "t2"]
                or p.components[0] != p.components[1]
            ):
                raise ValueError("Unsupported native predicate interpretation")

    class InferenceComplete(Exception):
        pass

    class Observed(getattr(native, CLASSES[method])):
        def determination(self, exps, data):
            result = super().determination(exps, data)
            caller = inspect.currentframe().f_back
            cell = caller.f_locals["cell"]
            column = self.schema.index(list(self.attr_index.keys())[cell[1]])
            values = result if isinstance(result, (list, tuple)) else [result]
            self.observed_candidates.append(
                {
                    "row": cell[0],
                    "col": column,
                    "values": [str(v) for v in values],
                    "native_return_type": type(result).__name__,
                }
            )
            del caller
            return result

        def repair(self, data, violations):
            self.initial_violations = len(violations)
            result = super().repair(data, violations)
            self.native_return_items = len(result)
            raise InferenceComplete()

    cleaner = Observed()
    cleaner.observed_candidates = []
    with (work / "native.log").open("w") as log:
        try:
            with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                cleaner.run(str(rule_file), str(dirty), str(dirty))
        except InferenceComplete:
            pass
        else:
            raise ValueError("Native repair did not reach completion hook")
        finally:
            if method == "bigdansing":
                native.tracemalloc.stop()
    if cleaner.schema != header:
        raise ValueError("Native parser changed columns")
    if set(cleaner.repaired_cells_value) != set(cleaner.repaired_cells):
        raise ValueError("Native detections and proposals disagree")
    frame = native.pd.read_csv(str(dirty))
    if method == "bigdansing":
        frame = frame.astype(str).fillna("nan")
    parsed_rows = list(csv.reader(io.StringIO(frame.to_csv(index=False))))[1:]
    if len(parsed_rows) != len(rows):
        raise ValueError("Native parser changed row count")
    for (i, j), value in cleaner.repaired_cells_value.items():
        frame.iloc[i, j] = value
    frame.to_csv(work / "repaired.csv", index=False)
    _, repaired = grid(work / "repaired.csv")
    proposals = [
        {"row": i, "col": j, "corrected_value": repaired[i][j]}
        for i, j in sorted(cleaner.repaired_cells_value)
    ]
    return {
        "changes": [p for p in proposals if p["corrected_value"] != rows[p["row"]][p["col"]]],
        "detections": [{"row": i, "col": j} for i, j in sorted(set(cleaner.repaired_cells))],
        "native_proposals": proposals,
        "candidate_history": cleaner.observed_candidates,
        "new_native_inference_runs": 1,
        "initial_violations": cleaner.initial_violations,
        "internal_parser_changed_cells": sum(
            v != rows[i][j] for i, r in enumerate(parsed_rows) for j, v in enumerate(r)
        ),
    }
