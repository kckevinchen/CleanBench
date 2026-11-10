"""Shared I/O for portable inference adapters; no benchmark labels are loaded here."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NATIVE_ROOT = ROOT / "native"


class ConfigurationError(RuntimeError):
    """A configuration failure that should stop the entire run."""


def read_json(path, default=None):
    path = Path(path)
    return json.loads(path.read_text()) if path.exists() else default


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temp.replace(path)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_table(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        header, *rows = csv.reader(stream)
    if not header or len(set(header)) != len(header) or any(len(r) != len(header) for r in rows):
        raise ValueError("Expected rectangular CSV with unique headers")
    return header, rows


def validate_changes(changes, headers, rows):
    seen = set()
    for change in changes:
        i, j, value = (change[k] for k in ("row", "col", "corrected_value"))
        if (
            type(i) is not int
            or type(j) is not int
            or not (0 <= i < len(rows) and 0 <= j < len(headers))
        ):
            raise ValueError("Prediction coordinate outside input table")
        if not isinstance(value, str) and value is not None:
            raise ValueError("Replacement must be a literal string or null")
        if (i, j) in seen:
            raise ValueError("Duplicate prediction coordinate")
        seen.add((i, j))
    return changes
