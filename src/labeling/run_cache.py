"""Bounded cache of run contexts with shared path validation."""

import threading
from collections import OrderedDict
from pathlib import Path

from .file_io import annotation_lock
from .run_context import RunContext
from .workspace import RunNotFound, resolve_run_dir


class RunCache:
    def __init__(self, outputs_dir: Path, *, max_entries: int = 32) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self.outputs_dir = outputs_dir.resolve()
        self.max_entries = max_entries
        self._cache: OrderedDict[str, RunContext] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, run_id: str) -> RunContext:
        directory = resolve_run_dir(self.outputs_dir, run_id)
        if not directory.is_dir():
            raise RunNotFound(f"Run not found: {run_id}")
        # Keep the same lock order as exports and store reads.
        with annotation_lock(directory), self._lock:
            context = self._cache.get(run_id)
            if context is None or context.is_stale():
                try:
                    context = RunContext(directory)
                except FileNotFoundError as exc:
                    raise RunNotFound(f"Run not found: {run_id}") from exc
                self._cache[run_id] = context
            self._cache.move_to_end(run_id)
            while len(self._cache) > self.max_entries:
                self._cache.popitem(last=False)
            return context

    def invalidate(self, run_id: str) -> None:
        with self._lock:
            self._cache.pop(run_id, None)
