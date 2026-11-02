"""Materialize reviewed column clusters into per-cell inconsistency labels."""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd

from src.core.data_loader import load_csv  # noqa: E402
from src.labeling.schema import (  # noqa: E402
    BenchmarkCell,
    ColumnClusters,
    ColumnLabelStatus,
)

logger = logging.getLogger("score_column_clusters")


# ---------------------------------------------------------------------
# Library API
# ---------------------------------------------------------------------


def _resolve_source_path(data_dir: Path, source: str) -> Optional[Path]:
    """Look up the CSV for ``source`` under ``data_dir``.

    Accepts both ``"foo"`` and ``"foo.csv"`` and tries the literal
    filename first, then the ``.csv`` suffix. Returns ``None`` when
    the file isn't found so the caller can warn-and-skip cleanly.
    """
    candidates = [source, f"{source}.csv"] if not source.endswith(".csv") else [source]
    for cand in candidates:
        path = data_dir / cand
        if path.is_file():
            return path
    return None


def _global_cluster_id(source: str, column: str, cluster_id: str) -> str:
    """Globally-unique cluster identifier for the emitted benchmark.

    A bare ``cluster_id`` (``"c1"``) is record-local; downstream
    cleaners need a stable handle that includes the (source, column)
    context. Using ``::`` as the separator matches the workspace's
    existing ``source::column`` convention in run dashboards.
    """
    return f"{source}::{column}::{cluster_id}"


def materialize_inconsistency_benchmark(
    records: Iterable[ColumnClusters],
    data_dir: Path,
    *,
    source_filter: Optional[str] = None,
    column_filter: Optional[str] = None,
    csv_cache: Optional[Dict[str, pd.DataFrame]] = None,
) -> List[BenchmarkCell]:
    """Return one :class:`BenchmarkCell` per matched cell.

    ``records`` should already be the latest-wins-reduced set per
    (source, column); pass ``store.latest_by_column().values()`` from
    a freshly-loaded :class:`ColumnClusterStore`.

    ``csv_cache`` (optional) lets a caller re-use loaded dataframes
    across calls. We never mutate the dataframes.

    Output shape per cell:
      * ``label="error"``
      * ``error_types=["inconsistency"]``
      * ``cluster_ids=[gid]`` and ``cluster_kinds=[cluster.kind]``
        (single-element lists — the unified schema uses lists for
        consistency with multi-cluster cells emitted by other
        detectors).
      * ``corrected_value`` is polymorphic: scalar canonical when
        the cluster has an operator-confirmed canonical (=>
        one-directional fix); sorted list of all distinct cluster
        values otherwise (=> bi-directional, downstream may map to
        any value including ``original_value``).
      * ``llm_suggested_value`` carries the LLM's proposed canonical
        (the cluster's ``llm_proposed_canonical``) as a hint,
        independent of whether the operator confirmed it.
    """
    cells: List[BenchmarkCell] = []
    cache: Dict[str, pd.DataFrame] = csv_cache if csv_cache is not None else {}
    stats = Counter()

    for rec in records:
        if rec.status != ColumnLabelStatus.LABELED:
            stats[f"skip_status_{rec.status.value}"] += 1
            continue
        if source_filter is not None and rec.source != source_filter:
            continue
        if column_filter is not None and rec.column != column_filter:
            continue

        # Load CSV once per source.
        if rec.source not in cache:
            path = _resolve_source_path(data_dir, rec.source)
            if path is None:
                logger.warning(
                    "Source CSV not found for %r under %s; skipping record.",
                    rec.source,
                    data_dir,
                )
                stats["skip_missing_csv"] += 1
                continue
            try:
                cache[rec.source] = load_csv(path)
            except Exception as exc:  # noqa: BLE001 - report-and-skip
                logger.warning(
                    "Failed to load CSV %s: %s; skipping record.",
                    path,
                    exc,
                )
                stats["skip_csv_load_error"] += 1
                continue
        df = cache[rec.source]

        if rec.column not in df.columns:
            logger.warning(
                "Column %r not present in %s; skipping record.",
                rec.column,
                rec.source,
            )
            stats["skip_missing_column"] += 1
            continue

        col_series = df[rec.column].astype(str)

        for cluster in rec.clusters:
            gid = _global_cluster_id(rec.source, rec.column, cluster.cluster_id)
            distinct_values = sorted(v.value for v in cluster.values)
            cluster_value_set = set(distinct_values)
            # Polymorphic ``corrected_value``: scalar canonical when
            # confirmed (=> one-directional); sorted list of distinct
            # surface forms otherwise (=> bi-directional).
            corrected: Any
            if cluster.canonical_value is not None:
                corrected = cluster.canonical_value
            else:
                corrected = distinct_values
            # Vectorised match: every row in col_series that's a member
            # of the cluster contributes one benchmark cell.
            mask = col_series.isin(cluster_value_set)
            matched_idx = list(col_series.index[mask])
            if not matched_idx:
                logger.warning(
                    "Cluster %s has no matching rows in %s/%s; " "labelling artifact may be stale.",
                    gid,
                    rec.source,
                    rec.column,
                )
                stats["empty_cluster_match"] += 1
                continue
            for ridx in matched_idx:
                original = col_series.at[ridx]
                cells.append(
                    BenchmarkCell(
                        source=rec.source,
                        row=int(ridx),
                        column=rec.column,
                        original_value=str(original),
                        label="error",
                        corrected_value=corrected,
                        llm_suggested_value=cluster.llm_proposed_canonical,
                        error_types=["inconsistency"],
                        cluster_ids=[gid],
                        cluster_kinds=[cluster.kind.value],
                        annotators=[rec.annotator],
                        note=rec.note,
                    )
                )
                stats["emit_cells"] += 1

    logger.info("scoring stats: %s", dict(stats))
    return cells
