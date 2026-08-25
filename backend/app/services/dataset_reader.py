from __future__ import annotations

import io
import os
import re
from typing import BinaryIO

import pandas as pd
import pyarrow.parquet as pq

from app.services.upload_limits import ensure_table_within_cell_budget


ALLOWED_EXTENSIONS = {"csv", "tsv", "txt", "xlsx", "parquet"}


def get_extension(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower().lstrip(".")
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {ext}")
    return ext


def make_columns_unique(columns: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    result: list[str] = []

    for col in columns:
        base = str(col)
        if base not in seen:
            seen[base] = 0
            result.append(base)
        else:
            seen[base] += 1
            result.append(f"{base}.{seen[base]}")
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
        "genes": "GeneNames",
        "genenames": "GeneNames",
        "pggenes": "GeneNames",
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
            df[col] = df[col].astype(str)

    return df


_CHUNK_ROWS = 50_000


def _rewind(fileobj: BinaryIO) -> None:
    try:
        fileobj.seek(0)
    except Exception:  # noqa: BLE001 - an unseekable stream is simply read once
        pass


def _read_delimited_within_budget(fileobj: BinaryIO, *, sep: str) -> pd.DataFrame:
    """Read a delimited table, refusing one that exceeds the cell budget.

    Delimited text is not compressed, so the byte limit bounds it loosely -- but a
    512 MB upload still expands to several GB as a frame. Reading in chunks caps
    the cost of an oversized file at one chunk beyond the budget rather than the
    whole thing, which is the same reasoning the parquet path applies to its
    footer metadata.
    """
    chunks: list[pd.DataFrame] = []
    rows = 0
    columns = 0
    for chunk in pd.read_csv(fileobj, sep=sep, chunksize=_CHUNK_ROWS):
        columns = len(chunk.columns)
        rows += len(chunk)
        ensure_table_within_cell_budget(rows, columns, label="Upload")
        chunks.append(chunk)
    if not chunks:
        _rewind(fileobj)
        return pd.read_csv(fileobj, sep=sep)
    return pd.concat(chunks, ignore_index=True) if len(chunks) > 1 else chunks[0]


def _ensure_workbook_within_budget(fileobj: BinaryIO) -> None:
    """Check an xlsx against the cell budget using its worksheet dimensions."""
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
            ensure_table_within_cell_budget(
                sheet.max_row or 0, sheet.max_column or 0, label="Upload"
            )
    finally:
        workbook.close()
        _rewind(fileobj)


def read_dataframe(filename: str, fileobj: BinaryIO) -> pd.DataFrame:
    ext = get_extension(filename)

    if ext in {"csv", "tsv", "txt"}:
        df = _read_delimited_within_budget(fileobj, sep="," if ext == "csv" else "\t")
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
        ensure_table_within_cell_budget(
            parquet_file.metadata.num_rows,
            parquet_file.metadata.num_columns,
            label="Upload",
        )
        df = parquet_file.read().to_pandas()
    else:
        raise ValueError(f"Unsupported file type: {ext}")

    ensure_table_within_cell_budget(len(df), len(df.columns), label="Upload")

    df = rename_cols(df)
    df = sanitize_dataframe(df)
    return df
