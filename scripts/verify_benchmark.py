"""Verify the released labels, source tables, coordinates and checksums offline."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from collections import Counter
from pathlib import Path

BENCHMARK = Path(__file__).resolve().parents[1] / "benchmark"


def verify(directory: Path = BENCHMARK) -> dict:
    manifest = json.loads((directory / "release_manifest.json").read_text())
    frozen_hash = "941c91fd13eee4a2ab7169e9a9fa3b833e9913530843719f91984e079011f3a2"
    if manifest["files"]["benchmark_cell.json"] != frozen_hash:
        raise ValueError("Cell labels differ from the frozen benchmark")
    for name, expected in manifest["files"].items():
        actual = hashlib.sha256((directory / name).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"Checksum mismatch: {name}")
    labels = [
        json.loads(line)
        for line in (directory / "benchmark_cell.json").read_text().splitlines()
        if line.strip()
    ]
    counts = Counter(r["status"] for r in labels)
    if counts != {"error": 1409, "ambiguous": 842}:
        raise ValueError(f"Unexpected cell counts: {counts}")
    if counts != manifest["cell_labels"]:
        raise ValueError("Cell counts differ from the release manifest")
    keys = [(r["dataset"], r["source"], r["row"], r["column"]) for r in labels]
    if len(set(keys)) != len(keys):
        raise ValueError("Duplicate benchmark cells")
    tables = {}
    with zipfile.ZipFile(directory / "sanitized_sources.zip") as archive:
        row_maps = {
            item["source"]: {
                original: exported for exported, original in enumerate(item["exported_to_source"])
            }
            for item in json.loads(archive.read("_ROW_MAP.json"))["sources"]
        }
        source_manifest = json.loads(archive.read("MANIFEST.json"))["sources"]
        names = [name for name in archive.namelist() if name.endswith(".csv")]
        if set(names) != set(source_manifest) or len(names) != 1000:
            raise ValueError("Source archive must contain the 1,000 declared tables")
        for name in names:
            content = archive.read(name)
            if hashlib.sha256(content).hexdigest() != source_manifest[name]["sha256"]:
                raise ValueError(f"Source checksum mismatch: {name}")
            rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))
            expected = source_manifest[name]
            if len(rows) - 1 != expected["rows"] or len(rows[0]) != expected["columns"]:
                raise ValueError(f"Source shape mismatch: {name}")
            tables[name] = rows
    for record in labels:
        name = f"{record['dataset']}/{record['source']}"
        table = tables[name]
        row = row_maps.get(record["source"], {}).get(record["row"], record["row"])
        column = [h.strip() for h in table[0]].index(record["column"])
        if table[row + 1][column].strip() != str(record["original_value"]).strip():
            raise ValueError(
                f"Original value mismatch: {name}, {record['row']}, {record['column']}"
            )
    pools = Counter(name.split("/")[0] for name in tables)
    cells = {
        pool: sum(
            (len(table) - 1) * len(table[0])
            for name, table in tables.items()
            if name.startswith(pool + "/")
        )
        for pool in pools
    }
    if dict(pools) != manifest["tables_by_dataset"] or cells != manifest["cells_by_dataset"]:
        raise ValueError("Source totals differ from the release manifest")
    if pools != {"pbi_500": 500, "bing21_500": 500} or sum(cells.values()) != 364804:
        raise ValueError("Unexpected source corpus totals")
    row_labels = [
        json.loads(line)
        for line in (directory / "benchmark_row.json").read_text().splitlines()
        if line.strip()
    ]
    if Counter(r["status"] for r in row_labels) != manifest["row_labels"]:
        raise ValueError("Row-label counts differ from the release manifest")
    return {
        "tables": len(tables),
        "cells": sum(cells.values()),
        "cell_labels": dict(counts),
        "row_labels": len(row_labels),
    }


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))
