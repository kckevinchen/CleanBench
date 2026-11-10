"""Published CleanBench inference bridge; see baselines/provenance.json."""

from __future__ import annotations

import csv
import importlib.util
import sys

from .native_correction import UPSTREAM

SOURCE_DIR = UPSTREAM / "BigDansing_Holistic"


CLASSES = {"bigdansing": "BigDansing", "holistic": "Holistic"}


def load_upstream(method):
    if method not in CLASSES:
        raise ValueError("Unknown native DC method")
    sys.path.insert(0, str(SOURCE_DIR))
    try:
        spec = importlib.util.spec_from_file_location(
            "cleanbench_native_" + method, SOURCE_DIR / (method + ".py")
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    module.PERFECTED, module.ONLYED = True, False
    return module


def grid(path):
    with path.open(newline="", encoding="utf-8") as stream:
        header, *rows = csv.reader(stream)
    if not rows or len(set(header)) != len(header) or any(len(row) != len(header) for row in rows):
        raise ValueError("Expected a nonempty rectangular table with unique headers")
    return header, rows
