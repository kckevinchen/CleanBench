"""Published CleanBench inference bridge; see baselines/provenance.json."""

from __future__ import annotations

import builtins
import contextlib
import time
from pathlib import Path

from baselines.common import atomic_json

from . import dc_blind as shared
from . import native_correction as original
from .dc_correction import grid
from .horizon_header_recovery import FDStream


def execute(method, dirty, rules, work):
    if method != "horizon":
        raise ValueError("This worker runs only native Horizon")
    header, rows = grid(dirty)
    if not rules:
        return {
            "changes": [],
            "detections": [],
            "native_proposals": [],
            "new_native_inference_runs": 0,
            "abstention": "no unary FDs",
            "mask_queries": 0,
        }
    if any(len(r["lhs"]) != 1 for r in rules):
        raise ValueError("The native Horizon reader supports unary FDs only")
    import pandas as pd

    frame = pd.read_csv(str(dirty))
    if list(frame.columns) != header or len(frame) != len(rows):
        raise ValueError("Native Horizon CSV parsing changed source coordinates")
    work.mkdir(parents=True, exist_ok=False)
    rule_path = work / "unary_fds.txt"
    mapping = {"C" + str(i): name for i, name in enumerate(header)}
    encoded = {name: token for token, name in mapping.items()}
    text = "".join(f"{encoded[r['lhs'][0]]} ⇒ {encoded[r['rhs']]}\n" for r in rules)
    rule_path.write_text(text, encoding="utf-8")
    native = original.load_horizon()
    # The known-location loader wraps pandas to preserve input strings. Blind
    # execution uses the release's original pandas parser, including its types.
    native.pd = pd
    native.PERFECTED, native.ONLYED = False, False
    trace = {"rule_file_reads": 0, "mask_queries": 0}

    class NoKnownLocations:
        def __contains__(self, cell):
            trace["mask_queries"] += 1
            raise ValueError("Blind Horizon must not consult known locations")

    native.gt_wrong_cells = NoKnownLocations()
    native.clean_df = None
    order = native.OrderFDs

    def observe_order(*args):
        result = order(*args)
        trace["ordered_source_fds"] = [
            {"left": fd.left, "right": fd.right, "left_scc": fd.lnum, "right_scc": fd.rnum}
            for fd in result
        ]
        return result

    def open_source(path, *args, **kwargs):
        if Path(path).resolve() == rule_path.resolve():
            if args or set(kwargs) - {"encoding"}:
                raise ValueError("Native Horizon rule-file access changed")
            trace["rule_file_reads"] += 1
            return FDStream(text, mapping)
        return builtins.open(path, *args, **kwargs)

    native.open, native.OrderFDs = open_source, observe_order
    atomic_json(
        work / "native_execution.json",
        {"started_at": time.time(), "perfected": False, "known_locations_supplied": False},
    )
    with (work / "native.log").open("w", encoding="utf-8") as log:
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            patterns = native.GeneratePatternPreservingRepairs(str(dirty), str(rule_path))
    if len(patterns) != len(rows) or trace["rule_file_reads"] != 4:
        raise ValueError("Native Horizon pattern or rule-read scope changed")
    cells = []
    for i, pattern in enumerate(patterns):
        for column, value in pattern.items():
            if type(column) is not str or column not in header or not isinstance(value, str):
                raise ValueError("Native Horizon returned an invalid pattern field")
            j = header.index(column)
            # This is the native calDetPrecRec comparison against DictReader's
            # source strings, restricted to attributes present in Rtable.
            if value != rows[i][j]:
                cells.append((i, j))
    atomic_json(work / "native_patterns.json", patterns)
    atomic_json(
        work / "native_detection.json",
        {"status": "complete", "dirty_sha256": shared.sha(dirty), "cells": sorted(cells)},
    )
    detections = shared.read_detection(dirty, work)
    before = work / "native_parsed.csv"
    # CRLF preserves exact strings even when headers/values contain bare CR.
    frame.to_csv(str(before), index=False, lineterminator="\r\n")
    _, parsed_rows = grid(before)
    for i, pattern in enumerate(patterns):
        for column, value in pattern.items():
            frame.loc[i, column] = value
    repaired_path = work / "native_repaired.csv"
    frame.to_csv(str(repaired_path), index=False, lineterminator="\r\n")
    repaired_header, repaired = grid(repaired_path)
    if repaired_header != header or len(repaired) != len(rows):
        raise ValueError("Native Horizon export changed source coordinates")
    proposals = [{"row": i, "col": j, "corrected_value": repaired[i][j]} for i, j in sorted(cells)]
    return {
        "changes": [p for p in proposals if p["corrected_value"] != rows[p["row"]][p["col"]]],
        "detections": detections,
        "native_proposals": proposals,
        "new_native_inference_runs": 1,
        "known_locations_supplied": False,
        "native_pattern_fields": sum(len(p) for p in patterns),
        "internal_parser_changed_cells": sum(
            value != rows[i][j] for i, row in enumerate(parsed_rows) for j, value in enumerate(row)
        ),
        "csv_record_separator": "CRLF",
        "header_serialization": "Decode positional FD tokens to exact source strings before graph construction",
        **trace,
    }
