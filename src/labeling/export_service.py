"""Consistent annotation materialization and isolated download snapshots."""

import shutil
import tempfile
from functools import wraps
from pathlib import Path

from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from ._cells import (
    _apply_exclusions_to_cells,
    _deduplicate_benchmark_cells,
    _make_value_resolver,
    _materialize_inconsistency_cells_for_export,
)
from .export import materialize_label_benchmark, materialize_skipped_cells
from .file_io import annotation_lock
from .reviewed_columns import materialize_column_skips
from .run_cache import RunCache
from .run_context import RunContext
from .schema import BenchmarkCell


def collect_cells(context: RunContext, *, deduplicate: bool = True) -> list[BenchmarkCell]:
    cells = materialize_label_benchmark(
        context.clusters,
        context.store,
        value_resolver=_make_value_resolver(context),
        cell_note_overrides=context.cell_notes_store.active_overrides(),
        row_verdict_overrides=context.row_verdict_store.active_overrides(),
    )
    cells.extend(_materialize_inconsistency_cells_for_export(context))
    cells = _apply_exclusions_to_cells(context, cells)
    return _deduplicate_benchmark_cells(cells) if deduplicate else cells


def download_transaction(cache: RunCache):
    """Serialize materialization, then stream an immutable, private copy.

    Canonical exports remain in the run for compatibility. Response-specific
    copies prevent a later export from changing a file before it is streamed.
    """

    def decorate(handler):
        @wraps(handler)
        def download(run_id: str, *args, **kwargs):
            context = cache.get(run_id)
            with annotation_lock(context.run_dir):
                response = handler(run_id, *args, **kwargs)
                if not isinstance(response, FileResponse):
                    return response
                directory = Path(tempfile.mkdtemp(prefix=".download-", dir=context.run_dir))
                try:
                    snapshot = directory / Path(response.path).name
                    shutil.copyfile(response.path, snapshot)
                    return FileResponse(
                        snapshot,
                        media_type=response.media_type,
                        filename=response.filename,
                        headers=dict(response.headers),
                        status_code=response.status_code,
                        background=BackgroundTask(shutil.rmtree, directory),
                    )
                except BaseException:
                    shutil.rmtree(directory, ignore_errors=True)
                    raise

        return download

    return decorate


def collect_skipped(context: RunContext, cells: list[BenchmarkCell]) -> list[BenchmarkCell]:
    keys = {(cell.source, cell.row, cell.column) for cell in cells}
    skipped = materialize_skipped_cells(
        context.clusters,
        context.store,
        value_resolver=_make_value_resolver(context),
        exclude_keys=keys,
    )
    skipped.extend(
        cell
        for cell in materialize_column_skips(context)
        if (cell.source, cell.row, cell.column) not in keys
    )
    return _deduplicate_benchmark_cells(_apply_exclusions_to_cells(context, skipped))
