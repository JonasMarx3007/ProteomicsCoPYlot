from __future__ import annotations

import os

from fastapi import UploadFile

_DEFAULT_UPLOAD_MAX_BYTES = 512 * 1024 * 1024
_CHUNK_BYTES = 1024 * 1024
_DEFAULT_UPLOAD_MAX_CELLS = 50_000_000


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
            "Filter or split the table before uploading."
        )
