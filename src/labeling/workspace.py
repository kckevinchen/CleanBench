"""Workspace identities and filesystem boundaries shared by services and routes."""

from pathlib import Path


class InvalidRunId(ValueError):
    """A run identity does not resolve to one child of the outputs directory."""


class RunNotFound(FileNotFoundError):
    """The requested annotation run does not exist."""


class RunDataError(ValueError):
    """A required run artifact exists but cannot be interpreted safely."""


class RunAlreadyExists(ValueError):
    """An import would overwrite an existing annotation run."""


def resolve_run_dir(outputs: Path, run_id: str) -> Path:
    if not run_id or run_id in {".", ".."} or any(c in run_id for c in "/\\\0"):
        raise InvalidRunId(f"Invalid run id: {run_id!r}")
    root = outputs.resolve()
    target = (root / run_id).resolve()
    if target.parent != root or target == root:
        raise InvalidRunId(f"Invalid run id: {run_id!r}")
    return target
