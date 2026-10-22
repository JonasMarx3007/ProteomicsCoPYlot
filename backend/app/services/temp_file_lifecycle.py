"""Release process-created temporary files after their last dataset/reference dies.

Weak references retain neither datasets nor their frames. Restore snapshots and
in-flight users keep the ordinary dataset objects alive, so rollback needs no
special deletion exception. Files left by a process crash use startup cleanup.
"""
from __future__ import annotations

import logging
import os
import stat
import weakref
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Iterator

LOGGER = logging.getLogger(__name__)
_DIRECTORIES = {"table_uploads", "peptide_uploads", "restore_uploads", "table_derived"}
_LOCK = RLock()
_SCOPE: ContextVar[list[Path] | None] = ContextVar("created_temp_files", default=None)


@dataclass
class _OwnedFile:
    identity: tuple[int, int]
    references: dict[int, weakref.ReferenceType[object]] = field(default_factory=dict)
    pins: int = 0


_FILES: dict[Path, _OwnedFile] = {}


def _safe_path(path: Path) -> Path | None:
    from app.services.managed_temp import managed_temp_root

    candidate = Path(os.path.abspath(path))
    root = Path(os.path.abspath(managed_temp_root()))
    if candidate.parent.parent != root or candidate.parent.name not in _DIRECTORIES:
        return None
    # Reject symlinks/junctions, including a redirected root. Never resolve a
    # candidate and then delete its target outside the application's directory.
    for part in (root, candidate.parent, candidate):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            return None
    if candidate.resolve() != candidate:
        return None
    return candidate


def register_created_file(path: Path, info: os.stat_result) -> None:
    """Called only for a file newly created by open_private, never an existing file."""
    candidate = _safe_path(path)
    if candidate is None or not stat.S_ISREG(info.st_mode):
        return
    with _LOCK:
        record = _OwnedFile((info.st_dev, info.st_ino))
        _FILES[candidate] = record
        scope = _SCOPE.get()
        if scope is not None:
            record.pins += 1
            scope.append(candidate)


def _release_unused(path: Path) -> None:
    # Caller holds _LOCK. An OS refusal is non-fatal; startup cleanup can retry.
    record = _FILES.get(path)
    if record is None or record.pins or record.references:
        return
    try:
        if _safe_path(path) is None:
            _FILES.pop(path, None)
            return
        info = path.lstat()
        if stat.S_ISREG(info.st_mode) and (info.st_dev, info.st_ino) == record.identity:
            path.unlink()
        _FILES.pop(path, None)
    except FileNotFoundError:
        _FILES.pop(path, None)
    except OSError:
        LOGGER.warning("Could not release an unused managed temporary file", exc_info=True)


def retain_temp_file(owner: object, path: str | Path | None) -> None:
    """Keep an owned file until this consumer is collected; shared paths are safe."""
    if not path:
        return
    candidate = Path(os.path.abspath(path))
    with _LOCK:
        record = _FILES.get(candidate)
        if record is None:
            return  # Local user files and files merely found on disk are not ours.
        key = id(owner)

        def released(reference: weakref.ReferenceType[object]) -> None:
            with _LOCK:
                current = _FILES.get(candidate)
                if current is record and current.references.get(key) is reference:
                    current.references.pop(key, None)
                    _release_unused(candidate)

        record.references[key] = weakref.ref(owner, released)


@contextmanager
def temporary_file_scope() -> Iterator[None]:
    """Clean failed/unattached writes, keeping files adopted by a live dataset."""
    created: list[Path] = []
    token = _SCOPE.set(created)
    try:
        yield
    finally:
        _SCOPE.reset(token)
        with _LOCK:
            for path in created:
                record = _FILES.get(path)
                if record is not None:
                    record.pins -= 1
                    _release_unused(path)
