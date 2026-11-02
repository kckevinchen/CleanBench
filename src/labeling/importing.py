"""Import local CSVs and cell candidates into an isolated annotation run."""

from __future__ import annotations

import csv
import io
import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .routers._context import RouterContext


def import_run(
    workspace: Path,
    run_id: str,
    sources: dict[str, str],
    candidates: list[dict[str, Any]] | None = None,
) -> Path:
    """Validate first, then create a run without changing existing labels.

    ``None`` candidates means review every cell. An explicit empty list creates
    an empty queue; missed errors can still be added from the source grid.
    """
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", run_id):
        raise ValueError("Use a run id of 1–100 letters, digits, dots, underscores or hyphens.")
    if not sources:
        raise ValueError("Select at least one UTF-8 CSV file.")
    tables: dict[str, list[list[str]]] = {}
    for name, text in sources.items():
        if Path(name).name != name or "/" in name or "\\" in name or not name.endswith(".csv"):
            raise ValueError(f"Expected a CSV basename: {name!r}")
        rows = list(csv.reader(io.StringIO(text.removeprefix("\ufeff"))))
        if len(rows) < 2 or not rows[0] or any(not h for h in rows[0]):
            raise ValueError(f"CSV needs nonempty headers and at least one data row: {name}")
        if len(set(rows[0])) != len(rows[0]):
            raise ValueError(f"Duplicate column names in {name}")
        if any(len(row) != len(rows[0]) for row in rows[1:]):
            raise ValueError(f"Inconsistent field count in {name}")
        tables[name] = rows
    if candidates is None:
        candidates = [
            {"source": name, "row": row, "column": column, "error_type": "manual_review"}
            for name, rows in tables.items()
            for row in range(len(rows) - 1)
            for column in rows[0]
        ]
    clusters = []
    seen = set()
    for index, candidate in enumerate(candidates):
        source, row, column = (candidate.get(k) for k in ("source", "row", "column"))
        if not isinstance(source, str) or source not in tables:
            raise ValueError(f"Unknown source in candidate {index + 1}: {source!r}")
        rows = tables[source]
        if type(row) is not int or not 0 <= row < len(rows) - 1 or column not in rows[0]:
            raise ValueError(f"Invalid cell in candidate {index + 1}: {(source, row, column)!r}")
        key = (source, row, column)
        if key in seen:
            raise ValueError(f"Duplicate candidate cell: {key!r}")
        seen.add(key)
        error_type = str(candidate.get("error_type") or "manual_review")
        explanation = str(candidate.get("explanation") or "Imported for manual review.")
        clusters.append(
            {
                "cluster_id": f"import-{index + 1:06d}",
                "source": source,
                "row": row,
                "columns": [column],
                "error_types": [error_type],
                "row_values": dict(zip(rows[0], rows[row + 1])),
                "detections": [
                    {
                        "source": source,
                        "row": row,
                        "columns": [column],
                        "error_type": error_type,
                        "explanation": explanation,
                        "observed": rows[row + 1][rows[0].index(column)],
                        "corrected_value": {column: candidate["suggested_value"]}
                        if candidate.get("suggested_value") is not None
                        else {},
                    }
                ],
            }
        )
    outputs = workspace.resolve() / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    target = outputs / run_id
    if target.exists():
        raise ValueError(f"Run already exists; choose a new id: {run_id}")
    staging = Path(tempfile.mkdtemp(prefix=".import-", dir=outputs))
    try:
        (staging / "sources").mkdir()
        for name, text in sources.items():
            (staging / "sources" / name).write_text(text, encoding="utf-8")
        summary = {
            "config": {
                "csv_paths": [f"sources/{name}" for name in sources],
                "sources": list(sources),
                "mode": "manual",
            }
        }
        (staging / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        (staging / "clusters.json").write_text(
            json.dumps(clusters, ensure_ascii=False, indent=2) + "\n"
        )
        # Atomic directory rename: never expose a half-imported run.
        staging.rename(target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return target


class ImportRequest(BaseModel):
    run_id: str
    sources: dict[str, str]
    candidates: list[dict[str, Any]] | None = Field(default=None)


def register_import_routes(app: FastAPI, ctx: RouterContext) -> None:
    @app.post("/api/import", status_code=201)
    def import_csvs(payload: ImportRequest) -> dict[str, str]:
        try:
            import_run(ctx.project_root, payload.run_id, payload.sources, payload.candidates)
        except (ValueError, csv.Error) as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"run_id": payload.run_id}
