"""Materialize explicit column-board decisions that have no per-cluster override."""

from .correction_suggester import (
    build_cluster_index,
    load_column_cluster_records,
    load_drafts,
    load_labels,
)
from .run_context import RunContext
from .schema import BenchmarkCell, ColumnLabelStatus, column_cluster_target_id


def materialize_reviewed_columns(context: RunContext) -> list[BenchmarkCell]:
    # Include tombstones: an explicit per-cluster decision takes precedence
    # over the broader column record, including an explicit decision to clear it.
    overrides = {label.target_id for label in context.store.all()}
    cells = []
    for record in context.column_cluster_store.latest_by_column().values():
        if record.status != ColumnLabelStatus.LABELED:
            continue
        frame = context.load_frame(record.source)
        for cluster in record.clusters:
            target = column_cluster_target_id(record.source, record.column, cluster.cluster_id)
            if target in overrides:
                continue
            values = sorted({item.value for item in cluster.values})
            correction = cluster.canonical_value if cluster.canonical_value is not None else values
            for row, original in enumerate(frame[record.column]):
                if original not in values or original == cluster.canonical_value:
                    continue
                cells.append(
                    BenchmarkCell(
                        source=record.source,
                        row=row,
                        column=record.column,
                        original_value=original,
                        label="error",
                        corrected_value=correction,
                        error_types=["inconsistency"],
                        cluster_ids=[f"{record.source}::{record.column}::{cluster.cluster_id}"],
                        cluster_kinds=[cluster.kind.value],
                        annotators=[record.annotator],
                        note=record.note,
                    )
                )
    return cells


def materialize_column_skips(context: RunContext) -> list[BenchmarkCell]:
    index = build_cluster_index(
        load_drafts(context.run_dir / "column_cluster_drafts.jsonl"),
        load_labels(context.run_dir / "labels.jsonl"),
        records=load_column_cluster_records(context.run_dir / "column_clusters.jsonl"),
    )
    cells = []
    for (source, column), groups in index.items():
        skipped = [group for group in groups if group.status == "skip"]
        if not skipped:
            continue
        frame = context.load_frame(source)
        for group in skipped:
            for row, original in enumerate(frame[column]):
                if original in group.value_set:
                    cells.append(
                        BenchmarkCell(
                            source=source,
                            row=row,
                            column=column,
                            original_value=original,
                            label="skip",
                            error_types=["inconsistency"],
                            cluster_ids=[group.global_id],
                            annotators=[group.annotator] if group.annotator else [],
                            note=group.note,
                        )
                    )
    return cells
