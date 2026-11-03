"""Shared state container passed to every router module's ``register()``.

The labelling workbench is a single-tenant FastAPI app: every endpoint
needs the same handful of project-scoped objects (caches, registries,
the job manager, the resolved outputs root). Wrapping them in this
dataclass lets each router module take one argument instead of seven.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException

from ..run_cache import RunCache
from ..runs import RunRegistry
from ..workspace import resolve_run_dir


@dataclass
class RouterContext:
    project_root: Path
    outputs_dir: Path
    static_dir: Path
    annotator: str
    registry: RunRegistry
    cache: RunCache

    # ------------------------------------------------------------------
    # Shared helpers (formerly closures in ``create_app``).
    # ------------------------------------------------------------------

    def safe_run_dir(self, run_id: str) -> Path:
        """Resolve ``outputs_dir / run_id``, rejecting traversal attempts.

        Symlinked run dirs whose target escapes the outputs root are
        rejected so ``shutil.rmtree`` and friends cannot follow them
        outside the workbench.
        """
        return resolve_run_dir(self.outputs_dir, run_id)

    def run_dir_or_404(self, run_id: str) -> Path:
        rd = self.safe_run_dir(run_id)
        if not rd.is_dir():
            raise HTTPException(404, f"run not found: {run_id}")
        return rd
