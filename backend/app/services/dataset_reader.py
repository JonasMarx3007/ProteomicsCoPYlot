from __future__ import annotations

import os
import re
from typing import BinaryIO

import pandas as pd
import pyarrow.parquet as pq

from app.services.upload_limits import (
    ensure_columns_within_budget,
    ensure_frame_bytes_within_budget,
    ensure_table_within_cell_budget,
)


ALLOWED_EXTENSIONS = {"csv", "tsv", "txt", "xlsx", "parquet"}


def get_extension(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower().lstrip(".")
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {ext}")
    return ext


def make_columns_unique(columns: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    result: list[str] = []
    occupied = {str(col) for col in columns}

    for col in columns:
        base = str(col)
        if base not in seen:
            seen[base] = 0
            result.append(base)
        else:
            seen[base] += 1
            candidate = f"{base}.{seen[base]}"
            while candidate in occupied:
                seen[base] += 1
                candidate = f"{base}.{seen[base]}"
            occupied.add(candidate)
            result.append(candidate)
    return result


def _normalize_colname(name: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name).strip().lower())


def rename_cols(df: pd.DataFrame) -> pd.DataFrame:
    # Trim whitespace first to make downstream aliasing predictable.
    renamed = df.copy()
    renamed.columns = [str(col).strip() for col in renamed.columns]

    alias_targets = {
        "run": "File.Name",
        "rfilename": "File.Name",
        "pgproteinnames": "ProteinNames",
        "pgproteingroups": "ProteinNames",
        "proteinids": "ProteinNames",
        "proteinnames": "ProteinNames",
        # FragPipe combined_protein.tsv: "Protein" (the full FASTA header) and
        # "Gene". "Protein ID" (the bare accession) stays as it is.
        "protein": "ProteinNames",
        "genes": "GeneNames",
        "genenames": "GeneNames",
        "pggenes": "GeneNames",
        "gene": "GeneNames",
        "pepstrippedsequence": "Stripped.Sequence",
        "egmodifiedsequence": "Modified.Sequence",
        "fgquantity": "Precursor.Quantity",
        "egrtpredicted": "Predicted.RT",
        "egapexrt": "RT",
    }

    current_columns = [str(col) for col in renamed.columns]
    occupied = set(current_columns)
    rename_map: dict[str, str] = {}
    for column in current_columns:
        target = alias_targets.get(_normalize_colname(column))
        if not target or target == column:
            continue
        # Avoid creating unnecessary duplicate canonical columns.
        if target in occupied:
            continue
        rename_map[column] = target
        occupied.add(target)
    return renamed.rename(columns=rename_map)


def sanitize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = make_columns_unique([str(c) for c in df.columns])

    for col in df.columns:
        if not pd.api.types.is_numeric_dtype(df[col]):
            # Keep missing cells missing. On pandas < 3, `astype(str)` writes
            # the words "nan"/"None" into them, and those then pass as gene or
            # protein names -- so the same file carried a gene called "nan" on
            # one pandas and no gene on another.
            column = df[col]
            df[col] = column.astype(str).where(column.notna(), None)

    return df


_CHUNK_ROWS = 50_000


def _rewind(fileobj: BinaryIO) -> None:
    try:
        fileobj.seek(0)
    except Exception:  # noqa: BLE001 - an unseekable stream is simply read once
        pass


def _stream_length(fileobj: BinaryIO) -> int | None:
    """Byte length of a seekable stream, or None when it cannot be measured."""
    try:
        current = fileobj.tell()
        fileobj.seek(0, 2)
        length = fileobj.tell()
        fileobj.seek(current)
        return int(length)
    except Exception:  # noqa: BLE001 - an unseekable stream is read in chunks instead
        return None


def _frame_bytes(frame: pd.DataFrame) -> int:
    """Materialised size of a frame, following object dtypes to the real strings."""
    try:
        return int(frame.memory_usage(deep=True).sum())
    except Exception:  # noqa: BLE001 - an exotic dtype should not defeat the budget
        return int(frame.memory_usage(deep=False).sum())


_NUL_SCAN_BYTES = 64 * 1024


def _reject_embedded_nul(fileobj: BinaryIO, filename: str) -> None:
    """Refuse delimited text carrying a NUL byte.

    pandas' C parser treats NUL as a terminator, so a header written as
    "Protein\x00Names" arrives as "Protein" -- the column is silently renamed and
    every later lookup for the real name misses. A NUL in what is meant to be
    UTF-8 text almost always means the file is UTF-16 or was truncated mid-write,
    so it is better refused than quietly repaired.

    Only the first chunk is scanned: that covers the header, where this actually
    bites, without reading a file the streaming budget exists to avoid.
    """
    try:
        fileobj.seek(0)
        head = fileobj.read(_NUL_SCAN_BYTES)
    except Exception:  # noqa: BLE001 - an unseekable stream is parsed as it comes
        return
    finally:
        _rewind(fileobj)
    if bytes([0]) in head:
        raise ValueError(
            f"Could not read {filename}: the file contains a NUL byte where text was "
            "expected, which usually means it is UTF-16 or was truncated. Re-save it "
            "as UTF-8 text."
        )


def _read_delimited_within_budget(fileobj: BinaryIO, *, sep: str, filename: str) -> pd.DataFrame:
    """Read a delimited table, stopping as soon as it exceeds a budget.

    Three things are bounded, because a file can grow in three directions and a
    check on one of them says nothing about the others: the column count, the
    cell count, and the bytes the frame actually occupies. Reading in chunks caps
    the cost of an oversized file at one chunk beyond the limit rather than the
    whole thing.
    """
    # Delimited text is not compressed, so its length on the wire is an honest
    # floor for what the frame will occupy -- a value costs at least its
    # characters, and usually more once it becomes a float or a Python string.
    # Checking it first stops a file of few but enormous rows, which row-based
    # chunking cannot: 400 rows is one chunk, so the chunk loop would read the
    # whole thing before it got to weigh any of it.
    raw_length = _stream_length(fileobj)
    if raw_length is not None:
        ensure_frame_bytes_within_budget(raw_length, label="Upload")
    _reject_embedded_nul(fileobj, filename)

    chunks: list[pd.DataFrame] = []
    rows = 0
    columns = 0
    nbytes = 0
    for chunk in pd.read_csv(fileobj, sep=sep, chunksize=_CHUNK_ROWS):
        columns = len(chunk.columns)
        # Checked on every chunk, not just the first: the width is known from the
        # header, and a wide file puts its whole width in that first chunk.
        ensure_columns_within_budget(columns, label="Upload")
        rows += len(chunk)
        ensure_table_within_cell_budget(rows, columns, label="Upload")
        nbytes += _frame_bytes(chunk)
        ensure_frame_bytes_within_budget(nbytes, label="Upload")
        chunks.append(chunk)
    if not chunks:
        _rewind(fileobj)
        return pd.read_csv(fileobj, sep=sep)
    return pd.concat(chunks, ignore_index=True) if len(chunks) > 1 else chunks[0]


def _ensure_workbook_within_budget(fileobj: BinaryIO) -> None:
    """Check an xlsx against the budgets before openpyxl materialises anything.

    An xlsx is a zip, and a zip's central directory carries each member's
    uncompressed size, so the expanded cost is knowable without decompressing.
    That is the measure the shape-only check missed: a workbook of a few cells
    holding megabytes of text each is small by row and column count.
    """
    try:
        import zipfile

        fileobj.seek(0)
        with zipfile.ZipFile(fileobj) as archive:
            expanded = sum(int(entry.file_size) for entry in archive.infolist())
        ensure_frame_bytes_within_budget(expanded, label="Upload")
    except ValueError:
        raise
    except Exception:  # noqa: BLE001 - a malformed zip is pandas' to report
        pass
    finally:
        _rewind(fileobj)

    try:
        import openpyxl

        workbook = openpyxl.load_workbook(fileobj, read_only=True)
    except ValueError:
        raise
    except Exception:  # noqa: BLE001 - let pandas report a malformed workbook
        _rewind(fileobj)
        return
    try:
        for sheet in workbook.worksheets:
            ensure_columns_within_budget(sheet.max_column or 0, label="Upload")
            ensure_table_within_cell_budget(
                sheet.max_row or 0, sheet.max_column or 0, label="Upload"
            )
    finally:
        workbook.close()
        _rewind(fileobj)


def _read_parquet_within_budget(parquet_file) -> pd.DataFrame:
    """Materialise a parquet file in batches, stopping if it exceeds the budget."""
    frames: list[pd.DataFrame] = []
    nbytes = 0
    for batch in parquet_file.iter_batches(batch_size=_CHUNK_ROWS):
        frame = batch.to_pandas()
        nbytes += _frame_bytes(frame)
        ensure_frame_bytes_within_budget(nbytes, label="Upload")
        frames.append(frame)
    if not frames:
        return parquet_file.read().to_pandas()
    return pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]


def _parse_dataframe(filename: str, fileobj: BinaryIO) -> pd.DataFrame:
    ext = get_extension(filename)

    if ext in {"csv", "tsv", "txt"}:
        df = _read_delimited_within_budget(fileobj, sep="," if ext == "csv" else "\t", filename=filename)
    elif ext == "xlsx":
        # xlsx is a compressed container too, so the shape is checked from the
        # worksheet dimensions before openpyxl materialises the cells.
        _ensure_workbook_within_budget(fileobj)
        df = pd.read_excel(fileobj)
    elif ext == "parquet":
        # Parquet carries its own shape, so the budget is checked before the frame
        # is materialised. Doing it afterwards would mean allocating the very
        # thing the limit exists to prevent.
        parquet_file = pq.ParquetFile(fileobj)
        metadata = parquet_file.metadata
        ensure_columns_within_budget(metadata.num_columns, label="Upload")
        ensure_table_within_cell_budget(
            metadata.num_rows, metadata.num_columns, label="Upload"
        )
        # The footer records each row group's uncompressed size. That is an
        # honest measure when values are distinct, and an undercount when they
        # repeat, because parquet dictionary encodes them -- a file reporting
        # 20 MB can still build 600 MB of separate Python strings. So it is a
        # cheap first refusal, not the only one.
        expanded = sum(
            metadata.row_group(index).total_byte_size
            for index in range(metadata.num_row_groups)
        )
        ensure_frame_bytes_within_budget(expanded, label="Upload")
        # The footer's uncompressed size is a floor, not the cost: identical
        # values are dictionary encoded, so a file that reports 20 MB can expand
        # past 600 MB once every row gets its own Python string. Read in batches
        # and measure what is actually built, stopping one batch past the limit.
        df = _read_parquet_within_budget(parquet_file)
    else:
        raise ValueError(f"Unsupported file type: {ext}")

    ensure_columns_within_budget(len(df.columns), label="Upload")
    ensure_table_within_cell_budget(len(df), len(df.columns), label="Upload")
    ensure_frame_bytes_within_budget(_frame_bytes(df), label="Upload")

    df = rename_cols(df)
    df = sanitize_dataframe(df)
    return df


_PARSE_HINTS = (
    ("no columns to parse", "the file is empty or has no header row"),
    ("codec can't decode", "the file is not valid UTF-8 text -- if it was exported from "
                           "Excel or instrument software, re-save it as UTF-8"),
    ("error tokenizing", "its rows do not all have the same number of columns"),
    ("excel file format cannot be determined", "it is named .xlsx but is not a valid workbook"),
)


def _readable_parse_error(filename: str, error: Exception) -> str:
    """Turn a parser's own words into something a biologist can act on."""
    text = str(error)
    lowered = text.lower()
    for needle, explanation in _PARSE_HINTS:
        if needle in lowered:
            return f"Could not read {filename}: {explanation}."
    return f"Could not read {filename}: {text}"


def read_dataframe(filename: str, fileobj: BinaryIO) -> pd.DataFrame:
    """Read an uploaded table, refusing one that is not a table at all.

    Two things go wrong here that used to be reported badly or not at all. A file
    that parses but holds no measurements -- a saved error page, a truncated
    export, a header with no rows -- was accepted with a success preview, and the
    user found out several screens later. And a parser's own exception text was
    passed straight through, so "Error tokenizing data. C error: Expected 3
    fields in line 3, saw 5" was the whole explanation offered.
    """
    try:
        frame = _parse_dataframe(filename, fileobj)
    except ValueError as error:
        # The upload budgets raise ValueError too, and those messages are already
        # written for the reader, so they must pass through untouched.
        if str(error).startswith(("Upload ", "Unsupported file type", "Could not read")):
            raise
        raise ValueError(_readable_parse_error(filename, error)) from error
    except Exception as error:  # noqa: BLE001 - a parser failure is the user's problem to fix
        raise ValueError(_readable_parse_error(filename, error)) from error

    if len(frame) == 0:
        raise ValueError(
            f"{filename} has no data rows. Check the export finished and that the "
            "header is the first line of the file."
        )
    if len(frame.columns) < 2:
        raise ValueError(
            f"{filename} has only {len(frame.columns)} column. A report table needs "
            "an identifier column and at least one measurement column -- check the "
            "file is not a saved web page and that the separator is correct."
        )
    return frame
