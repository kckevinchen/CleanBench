"""Published CleanBench inference bridge; see baselines/provenance.json."""

from __future__ import annotations

import copy
import sys
from types import SimpleNamespace

from baselines.common import (
    read_json,
)

from .daisy_native import load_core


def point_inference(work, locations=None):
    """Rehydrate saved domains and run original merging/selection, not detection.

    The missing no-overlap output is obtained by calling the release's public
    final_result on its already-merged local result. The function bodies remain
    unchanged. With known locations, other domains become original-value
    singletons before the native multi-rule probability/selection stage.
    """
    header = read_json(work / "columns.json")
    plans = read_json(work / "rules.json")
    parsed = read_json(work / "native_input.json")
    if not plans or not parsed or not header or len(header) != len(set(header)):
        raise ValueError("Saved Daisy candidate inputs are incomplete")
    aliases = ["C%d" % j for j in range(len(header))]
    if any(len(row) != len(header) or any(not isinstance(v, str) for v in row) for row in parsed):
        raise ValueError("Saved Daisy native strings have invalid source coordinates")
    mask = None if locations is None else set()
    if locations is not None:
        for cell in locations:
            if len(cell) != 2 or any(type(v) is not int for v in cell):
                raise ValueError("Known locations must be integer row/column pairs")
            row, col = cell
            if not (0 <= row < len(parsed) and 0 <= col < len(header)) or (row, col) in mask:
                raise ValueError("Known locations are duplicate or outside the source grid")
            mask.add((row, col))
    with load_core() as native:
        dataset = native.dataset(str(work / "dirty.csv"))
        before = dataset.df.copy(deep=True)
        if (
            list(before.columns) != ["index"] + aliases
            or before.iloc[:, 1:].values.tolist() != parsed
        ):
            raise ValueError("Rehydrated native parser differs from the saved detection input")
        sigmas, dcs = [], []
        projected = 0
        for index, plan in enumerate(plans):
            record = read_json(work / "rules" / ("%03d.json" % index))
            if record["status"] != "complete" or record["rule"] != plan:
                raise ValueError("Saved native rule candidates are incomplete or mismatched")
            dcs.append(native.DCRule(plan["text"], plan["schema"]))
            expected = {str(j) for j in plan["source_columns"]}
            rows = {}
            for item in record["probabilistic_candidates"]:
                row = item["row"]
                if type(row) is not int or row in rows or not 0 <= row < len(parsed):
                    raise ValueError("Saved candidate lost its source row identity")
                if set(item["domains"]) != expected:
                    raise ValueError("Saved candidate columns differ from the native rule schema")
                series = dataset.df.loc[row].copy(deep=True)
                for column, domain in item["domains"].items():
                    col = int(column)
                    if mask is not None and (row, col) not in mask:
                        series[aliases[col]] = {parsed[row][col]: 1.0}
                        projected += 1
                    else:
                        series[aliases[col]] = copy.deepcopy(domain)
                rows[row] = series
            if set(rows) != set(range(len(parsed))):
                raise ValueError("Saved native domains do not cover the full source table")
            sigmas.append(SimpleNamespace(relax_full=rows))
        observed = {}
        original_profile = sys.getprofile()
        function = native.MultiCleanSigma.multiRelaxDC.__code__

        def observe(frame, event, arg):
            if event == "return" and frame.f_code is function:
                observed["result_list"] = frame.f_locals["result_list"]

        try:
            sys.setprofile(observe)
            multi = native.MultiCleanSigma(dataset, sigmas, dc_list=dcs)
        finally:
            sys.setprofile(original_profile)
        completed_missing_tail = not hasattr(multi, "relax_result")
        selected = (
            multi.final_result(observed["result_list"])
            if completed_missing_tail
            else multi.relax_result
        )
        if not dataset.df.equals(before):
            raise ValueError("Native point inference unexpectedly mutated its context dataframe")
        changes, final_rows, seen = [], [], set()
        invalid = []
        active_values = [set(row[j] for row in parsed) for j in range(len(header))]
        for series in selected.values():
            row = int(series["index"])
            if row != series.name or row in seen or not 0 <= row < len(parsed):
                raise ValueError("Native point selection changed source row identity")
            seen.add(row)
            final = []
            for col, alias in enumerate(aliases):
                value = series[alias]
                if not isinstance(value, str):
                    raise ValueError("Native point selector did not return literal strings")
                final.append(value)
                if value == parsed[row][col]:
                    continue
                if value.startswith(("!", "<", ">")) or value not in active_values[col]:
                    invalid.append({"row": row, "col": col, "selected": value})
                if mask is not None and (row, col) not in mask:
                    raise ValueError("Native point inference changed an unmarked cell")
                changes.append({"row": row, "col": col, "corrected_value": value})
            final_rows.append({"row": row, "values": final})
        if seen != set(range(len(parsed))):
            raise ValueError("Native point selection lost source rows")
        return {
            "changes": sorted(changes, key=lambda c: (c["row"], c["col"])),
            "selected_rows": sorted(final_rows, key=lambda item: item["row"]),
            "nonliteral_selections": invalid,
            "projected_unmarked_domains": projected,
            "completed_native_no_overlap_tail": completed_missing_tail,
            "new_candidate_generation_runs": 0,
            "native_point_inference_runs": 1,
        }
