"""Atomic file publication and per-run annotation coordination."""

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from filelock import FileLock


def annotation_lock(directory: Path) -> FileLock:
    # A singleton permits an export transaction to read stores reentrantly
    # while preserving independent lock ownership for other threads.
    return FileLock(
        str(directory.resolve() / ".annotations.lock"),
        timeout=30,
        is_singleton=True,
        thread_local=True,
    )


@contextmanager
def atomic_path(destination: Path) -> Iterator[Path]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(fd)
    temporary = Path(name)
    try:
        yield temporary
        with temporary.open("rb+") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_text(destination: Path, content: str) -> None:
    with atomic_path(destination) as temporary:
        temporary.write_text(content, encoding="utf-8", newline="")
