"""Published CleanBench inference bridge; see baselines/provenance.json."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent


def predictions(result: dict, rows: list[list[str]], dataset: str, detector: str) -> dict:
    """Validate native coordinates and keep initial detection separate from edits."""
    if result.get("status") != "complete":
        raise ValueError("Native result is not complete")
    cleaned = result["cleaned_rows"]
    if len(cleaned) != len(rows) or any(len(a) != len(b) for a, b in zip(rows, cleaned)):
        raise ValueError("Native repair changed source shape")
    cells = set()
    for row, col in result["initial_detections"]:
        if type(row) is not int or type(col) is not int:
            raise ValueError("Native coordinate is not an integer")
        if not (0 <= row < len(rows) and 0 <= col < len(rows[row])):
            raise ValueError("Native coordinate is outside the source table")
        cells.add((row, col))
    base = {"dataset": dataset, "detector": detector}
    detected = [{**base, "row": row, "col": col} for row, col in sorted(cells)]
    repairs = []
    for i, (before, after) in enumerate(zip(rows, cleaned)):
        for j, (old, new) in enumerate(zip(before, after)):
            if not isinstance(new, str):
                raise ValueError("Native SQL NULL repair needs an explicit output convention")
            if old != new:
                repairs.append({**base, "row": i, "col": j, "corrected_value": new})
    return {"detection": detected, "e2e": repairs}
