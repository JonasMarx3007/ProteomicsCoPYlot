from __future__ import annotations

import io
import os
from typing import BinaryIO

import pandas as pd
import pyarrow.parquet as pq


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


def rename_cols(df: pd.DataFrame) -> pd.DataFrame:
    rename_map = {
        "Run": "File.Name",
        "PG.ProteinNames": "ProteinNames",
        "PG.ProteinGroups": "ProteinNames",
        "Protein.IDs": "ProteinNames",
        "PG.Genes": "GeneNames",
        "Protein.Names": "ProteinNames",
        "Protein IDs": "ProteinNames",
    }
    return df.rename(columns=rename_map)


def sanitize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = make_columns_unique([str(c) for c in df.columns])

    for col in df.columns:
        if not pd.api.types.is_numeric_dtype(df[col]):
            df[col] = df[col].astype(str)

    return df


def read_dataframe(filename: str, fileobj: BinaryIO) -> pd.DataFrame:
    ext = get_extension(filename)

    if ext == "csv":
        df = pd.read_csv(fileobj)
    elif ext in {"tsv", "txt"}:
        df = pd.read_csv(fileobj, sep="\t")
    elif ext == "xlsx":
        df = pd.read_excel(fileobj)
    elif ext == "parquet":
        table = pq.read_table(fileobj)
        df = table.to_pandas()
    else:
        raise ValueError(f"Unsupported file type: {ext}")

    df = rename_cols(df)
    df = sanitize_dataframe(df)
    return df