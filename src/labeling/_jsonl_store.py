"""Durable append-only JSONL histories with thread and process coordination.

Writers use a sidecar lock, complete short writes, and fsync before reporting
success. Malformed history is preserved; a missing final newline is repaired
by appending a separator, so a crash cannot swallow the next valid record.
"""

from __future__ import annotations

import logging
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Generic, Iterator, TypeVar

from filelock import FileLock
from pydantic import BaseModel, ValidationError

from .file_io import annotation_lock

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)
K = TypeVar("K")
FileSignature = tuple[int, int, int, int]


class JsonlStore(Generic[T, K]):
    """Latest-wins index over an append-only history, shared by all stores."""

    model: type[T]

    def __init__(self, path: Path) -> None:
        self.path = Path(path).resolve()
        self._lock = threading.Lock()
        self._file_lock = FileLock(str(self.path) + ".lock", timeout=30)
        self._records: list[T] = []
        self._latest: dict[K, T] = {}
        self._file_sig: FileSignature | None = None
        self.reload()

    def _key(self, record: T) -> K:
        raise NotImplementedError

    @staticmethod
    def _signature(stat: os.stat_result) -> FileSignature:
        return stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_size

    def _current_sig(self) -> FileSignature | None:
        try:
            return self._signature(self.path.stat())
        except FileNotFoundError:
            return None

    @contextmanager
    def _synchronized(self, *, create: bool = False) -> Iterator[None]:
        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.parent.exists():
            with annotation_lock(self.path.parent):
                with self._lock, self._file_lock:
                    yield
        else:
            with self._lock:
                yield

    def _reload_locked(self) -> None:
        records: list[T] = []
        latest: dict[K, T] = {}
        signature = None
        try:
            stream = self.path.open("r", encoding="utf-8", errors="replace")
        except FileNotFoundError:
            stream = None
        if stream is not None:
            with stream:
                for line_no, line in enumerate(stream, start=1):
                    if not line.strip():
                        continue
                    try:
                        record = self.model.model_validate_json(line)
                    except ValidationError:
                        logger.warning(
                            "Ignoring malformed history record in %s at line %d", self.path, line_no
                        )
                        continue
                    records.append(record)
                    latest[self._key(record)] = record
                signature = self._signature(os.fstat(stream.fileno()))
        self._records, self._latest, self._file_sig = records, latest, signature

    def _refresh_locked(self) -> None:
        if self._current_sig() != self._file_sig:
            self._reload_locked()

    def reload(self) -> None:
        with self._synchronized():
            self._reload_locked()

    def _reload_if_changed(self) -> None:
        with self._synchronized():
            self._refresh_locked()

    @staticmethod
    def _write_all(fd: int, payload: bytes) -> None:
        remaining = memoryview(payload)
        while remaining:
            written = os.write(fd, remaining)
            if written <= 0:
                raise OSError("History write made no progress")
            remaining = remaining[written:]

    def _write_lines_locked(self, payload: str) -> None:
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            if os.lseek(fd, 0, os.SEEK_END):
                os.lseek(fd, -1, os.SEEK_END)
                if os.read(fd, 1) != b"\n":
                    self._write_all(fd, b"\n")
            self._write_all(fd, payload.encode("utf-8"))
            os.fsync(fd)
        except BaseException:
            # The next operation must inspect any partially written tail.
            self._file_sig = None
            raise
        finally:
            os.close(fd)

    def _append(self, record: T) -> T:
        self._append_many([record])
        return record

    def _append_many(self, records: list[T]) -> list[T]:
        if not records:
            return []
        payload = "".join(record.model_dump_json() + "\n" for record in records)
        with self._synchronized(create=True):
            self._refresh_locked()
            self._write_lines_locked(payload)
            for record in records:
                self._records.append(record)
                self._latest[self._key(record)] = record
            self._file_sig = self._current_sig()
        return list(records)

    def _all(self) -> list[T]:
        with self._synchronized():
            self._refresh_locked()
            return list(self._records)

    def _latest_map(self) -> dict[K, T]:
        with self._synchronized():
            self._refresh_locked()
            return dict(self._latest)

    def _latest_get(self, key: K) -> T | None:
        with self._synchronized():
            self._refresh_locked()
            return self._latest.get(key)
