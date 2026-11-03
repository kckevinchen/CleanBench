"""Validate and publish portable annotation runs without HTTP dependencies."""

from __future__ import annotations

import csv
import io
import json
import re
import shutil
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from filelock import FileLock

from .file_io import atomic_write_text
from .import_models import ImportCandidate
from .workspace import RunAlreadyExists, resolve_run_dir


@dataclass
class SourceTable:
    text: str
    headers: list[str]
    rows: list[list[str]]


def parse_sources(sources: Mapping[str, str]) -> dict[str, SourceTable]:
    if not sources:
        raise ValueError("Select at least one UTF-8 CSV file.")
    tables = {}
    for name, text in sources.items():
        if Path(name).name != name or "/" in name or "\\" in name or not name.endswith(".csv"):
            raise ValueError(f"Expected a CSV basename: {name!r}")
        if not isinstance(text, str) or "\0" in text:
            raise ValueError(f"Expected UTF-8 text without NUL bytes: {name}")
        text.encode("utf-8")
        try:
            rows = list(
                csv.reader(io.StringIO(text.removeprefix("\ufeff"), newline=""), strict=True)
            )
        except csv.Error as exc:
            raise ValueError(f"Malformed CSV {name}: {exc}") from exc
        if len(rows) < 2:
            raise ValueError(f"CSV needs headers and at least one data row: {name}")
        headers = [header.strip() for header in rows[0]]
        if not headers or any(not header for header in headers):
            raise ValueError(f"CSV needs nonempty column names: {name}")
        if len(set(headers)) != len(headers):
            raise ValueError(f"Duplicate column names after whitespace normalization: {name}")
        if any(len(row) != len(headers) for row in rows[1:]):
            raise ValueError(f"Inconsistent field count in {name}")
        tables[name] = SourceTable(text, headers, rows[1:])
    return tables


def build_clusters(
    tables: dict[str, SourceTable],
    candidates: Iterable[ImportCandidate | dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    if candidates is None:
        candidates = (
            {"source": name, "row": row, "column": column}
            for name, table in tables.items()
            for row in range(len(table.rows))
            for column in table.headers
        )
    clusters = []
    seen = set()
    for index, raw in enumerate(candidates, start=1):
        candidate = ImportCandidate.model_validate(raw)
        source, row, column = candidate.source, candidate.row, candidate.column
        table = tables.get(source)
        if table is None:
            raise ValueError(f"Unknown source in candidate {index}: {source!r}")
        if row >= len(table.rows) or column not in table.headers:
            raise ValueError(f"Invalid cell in candidate {index}: {(source, row, column)!r}")
        key = (source, row, column)
        if key in seen:
            raise ValueError(f"Duplicate candidate cell: {key!r}")
        seen.add(key)
        observed = table.rows[row][table.headers.index(column)].strip()
        clusters.append(
            {
                "cluster_id": f"import-{index:06d}",
                "source": source,
                "row": row,
                "columns": [column],
                "error_types": [candidate.error_type],
                "row_values": {column: observed},
                "detections": [
                    {
                        "source": source,
                        "row": row,
                        "columns": [column],
                        "error_type": candidate.error_type,
                        "explanation": candidate.explanation,
                        "observed": observed,
                        "corrected_value": {column: candidate.suggested_value}
                        if candidate.suggested_value is not None
                        else {},
                    }
                ],
            }
        )
    return clusters


def import_run(
    workspace: Path,
    run_id: str,
    sources: Mapping[str, str],
    candidates: Sequence[ImportCandidate | dict[str, Any]] | None = None,
) -> Path:
    """Validate before touching disk; atomically publish without replacing a run."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", run_id):
        raise ValueError("Use a run id of 1–100 letters, digits, dots, underscores or hyphens.")
    tables = parse_sources(sources)
    clusters = build_clusters(tables, candidates)
    outputs = workspace.resolve() / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    target = resolve_run_dir(outputs, run_id)
    staging = Path(tempfile.mkdtemp(prefix=".import-", dir=outputs))
    try:
        for name, table in tables.items():
            atomic_write_text(staging / "sources" / name, table.text)
        summary = {
            "config": {
                "csv_paths": [f"sources/{name}" for name in sources],
                "sources": list(sources),
                "mode": "manual",
            }
        }
        atomic_write_text(staging / "summary.json", json.dumps(summary, indent=2) + "\n")
        atomic_write_text(
            staging / "clusters.json", json.dumps(clusters, ensure_ascii=False, indent=2) + "\n"
        )
        with FileLock(str(outputs / ".imports.lock"), timeout=30):
            if target.exists() or target.is_symlink():
                raise RunAlreadyExists(f"Run already exists; choose a new id: {run_id}")
            staging.rename(target)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return target
