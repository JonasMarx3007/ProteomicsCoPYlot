from __future__ import annotations

import os
from pathlib import Path

from fastapi import UploadFile

_DEFAULT_UPLOAD_MAX_BYTES = 64 * 1024**3
_CHUNK_BYTES = 1024 * 1024
_DEFAULT_UPLOAD_MAX_CELLS = 10_000_000_000
_FALLBACK_FRAME_BYTES = 1024**3
_DEFAULT_UPLOAD_MAX_COLUMNS = 20_000


def upload_max_bytes() -> int:
    raw = str(os.getenv("COPYLOT_UPLOAD_MAX_BYTES", "")).strip()
    if not raw:
        return _DEFAULT_UPLOAD_MAX_BYTES
    try:
        parsed = int(raw)
    except ValueError:
        return _DEFAULT_UPLOAD_MAX_BYTES
    return max(1, parsed)


def upload_size_bytes(
    file: UploadFile,
    *,
    label: str = "Upload",
    max_bytes: int | None = None,
) -> int:
    """Measure an upload without consuming seekable streams and enforce a bound."""
    limit = upload_max_bytes() if max_bytes is None else max(1, int(max_bytes))
    size = getattr(file, "size", None)
    if isinstance(size, int):
        if size > limit:
            raise ValueError(f"{label} exceeds the configured upload limit.")
        return max(0, size)

    stream = getattr(file, "file", None)
    if stream is None or not hasattr(stream, "read"):
        raise ValueError(f"{label} size could not be determined safely.")
    try:
        position = stream.tell()
        stream.seek(0)
    except Exception:  # noqa: BLE001 - unseekable streams can still be bounded
        position = None
    try:
        observed = 0
        while True:
            chunk = stream.read(_CHUNK_BYTES)
            if not chunk:
                break
            observed += len(chunk)
            if observed > limit:
                raise ValueError(f"{label} exceeds the configured upload limit.")
        return observed
    finally:
        if position is not None:
            try:
                stream.seek(position)
            except Exception:  # noqa: BLE001 - best effort rewind
                pass


def ensure_upload_size(file: UploadFile, *, label: str = "Upload") -> None:
    """Reject an upload larger than the configured limit.

    `UploadFile.size` alone is not enough: it is populated only after the
    multipart parser has already buffered the file, and it is `None` for some
    streamed encodings -- in which case the check silently passed and the limit
    did nothing. So the size is used when present, and otherwise the stream is
    measured directly by reading one byte past the limit, which is the pattern
    already used for restore uploads.
    """
    upload_size_bytes(file, label=label)


def upload_max_cells() -> int:
    """Row x column budget for a parsed table.

    The byte limit measures the upload as it arrives, which is compressed for
    parquet and xlsx. A 0.27 MB parquet of constant values expands past 1 GB once
    materialised, so the byte limit alone does not bound memory. This budget is
    applied to the parsed shape instead, and mirrors the cap the restore path
    already enforces.
    """
    raw = str(os.getenv("COPYLOT_UPLOAD_MAX_CELLS", "")).strip()
    if not raw:
        return _DEFAULT_UPLOAD_MAX_CELLS
    try:
        parsed = int(raw)
    except ValueError:
        return _DEFAULT_UPLOAD_MAX_CELLS
    return max(1, parsed)


def ensure_table_within_cell_budget(rows: int, columns: int, *, label: str = "Upload") -> None:
    """Reject a table whose parsed shape would exceed the cell budget."""
    budget = upload_max_cells()
    cells = max(0, int(rows)) * max(0, int(columns))
    if cells > budget:
        raise ValueError(
            f"{label} expands to {rows:,} rows x {columns:,} columns "
            f"({cells:,} cells), above the {budget:,} cell limit. "
            "Use a smaller table or ask the administrator to adjust COPYLOT_UPLOAD_MAX_CELLS."
        )


def upload_max_frame_bytes() -> int:
    """Budget for the materialised table, in bytes.

    Rows x columns measures the table's shape, and memory does not care about
    shape. A file of 200 cells holding 2 MiB of text each is 200 cells against a
    generous cell budget and still costs hundreds of megabytes. Counting bytes is
    the one bound that does not depend on which dimension a file chose to grow.
    """
    raw = str(os.getenv("COPYLOT_UPLOAD_MAX_FRAME_BYTES", "")).strip()
    try:
        if raw:
            return max(1, int(raw))
    except ValueError:
        pass
    capacity = _memory_capacity_bytes()
    # Parsing, normalization and annotation retain additional copies of a table.
    return min(128 * 1024**3, max(1, capacity // 4)) if capacity else _FALLBACK_FRAME_BYTES


def _memory_capacity_bytes() -> int | None:
    """Physical RAM, constrained by the container budget when one is visible."""
    try:
        if os.name == 'nt':
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [('length', ctypes.c_uint32), ('load', ctypes.c_uint32)] + [
                    (name, ctypes.c_uint64) for name in ('total_phys', 'avail_phys', 'total_page',
                        'avail_page', 'total_virtual', 'avail_virtual', 'avail_extended')]

            status = MemoryStatus()
            status.length = ctypes.sizeof(status)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return None
            capacity = int(status.total_phys)
        else:
            capacity = int(os.sysconf('SC_PHYS_PAGES')) * int(os.sysconf('SC_PAGE_SIZE'))
    except (AttributeError, OSError, ValueError):
        return None
    for path in ('/sys/fs/cgroup/memory.max', '/sys/fs/cgroup/memory/memory.limit_in_bytes'):
        try:
            limit = int(Path(path).read_text().strip())
            if limit > 0:
                capacity = min(capacity, limit)
        except (OSError, ValueError):
            pass
    return capacity if capacity > 0 else None


def upload_max_columns() -> int:
    """Column cap for a parsed table.

    A frame carries per-column overhead that no byte count of the data sees, so a
    file of one row and 300,000 columns is cheap by every other measure and still
    expensive to hold. No proteomics report has more columns than it has samples
    plus a handful of annotations.
    """
    raw = str(os.getenv("COPYLOT_UPLOAD_MAX_COLUMNS", "")).strip()
    if not raw:
        return _DEFAULT_UPLOAD_MAX_COLUMNS
    try:
        parsed = int(raw)
    except ValueError:
        return _DEFAULT_UPLOAD_MAX_COLUMNS
    return max(1, parsed)


def ensure_frame_bytes_within_budget(nbytes: int, *, label: str = "Upload") -> None:
    """Reject a table whose materialised size exceeds the byte budget."""
    budget = upload_max_frame_bytes()
    measured = max(0, int(nbytes))
    if measured > budget:
        raise ValueError(
            f"{label} expands to {measured / 1048576:,.0f} MB in memory, above the "
            f"{budget / 1048576:,.0f} MB limit. A small file can still expand a long "
            "way if its cells hold large text. Use a machine with more RAM, reduce the table, "
            "or configure COPYLOT_UPLOAD_MAX_FRAME_BYTES for a suitably sized server."
        )


def ensure_columns_within_budget(columns: int, *, label: str = "Upload") -> None:
    """Reject a table with more columns than any real report carries."""
    budget = upload_max_columns()
    measured = max(0, int(columns))
    if measured > budget:
        raise ValueError(
            f"{label} has {measured:,} columns, above the {budget:,} column limit. "
            "Check the file is a report table and not a transposed or malformed export."
        )
