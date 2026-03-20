from __future__ import annotations

import contextlib
import io
import os

import pandas as pd

from app.schemas.external import PeptideCollapseRequest, PeptideCollapseResponse
from app.services.external_functions import (
    peptideCollapse,
    peptideCollapse_old,
    process_and_export,
)


def _normalize_path(path: str) -> str:
    return path.strip().strip('"').strip("'")


def _resolve_output_path(input_path: str, output_path: str | None) -> str:
    if output_path:
        return output_path
    base_name, _ = os.path.splitext(input_path)
    return f"{base_name}_collapsed.tsv"


def _extract_error(logs: str) -> str | None:
    for line in reversed(logs.splitlines()):
        text = line.strip()
        if text.lower().startswith("an error occurred:"):
            _, _, message = text.partition(":")
            return message.strip() or text
    return None


def run_peptide_collapse(payload: PeptideCollapseRequest) -> PeptideCollapseResponse:
    input_path = _normalize_path(payload.inputPath)
    output_path = _normalize_path(payload.outputPath) if payload.outputPath else None

    if not input_path:
        raise ValueError("Input file path is required.")
    if not os.path.exists(input_path):
        raise ValueError(f"Input file not found: {input_path}")

    collapse_func = peptideCollapse if payload.collapseVersion == "newest" else peptideCollapse_old
    resolved_output_path = _resolve_output_path(input_path, output_path)

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        process_and_export(
            input_path,
            output_path=output_path,
            cutoff=payload.cutoff,
            collapse_func=collapse_func,
        )

    logs = buffer.getvalue()
    success = (
        "File processed and exported successfully." in logs
        and os.path.exists(resolved_output_path)
    )

    rows: int | None = None
    columns: int | None = None
    column_names: list[str] = []
    preview: list[dict[str, object]] = []
    if success:
        frame = pd.read_csv(resolved_output_path, sep="\t")
        rows = len(frame)
        columns = len(frame.columns)
        column_names = [str(column) for column in frame.columns]
        preview_frame = frame.head(30).where(pd.notna(frame.head(30)), None)
        preview = preview_frame.to_dict(orient="records")

    error = None if success else (_extract_error(logs) or "Peptide collapse did not complete successfully.")

    return PeptideCollapseResponse(
        success=success,
        inputPath=input_path,
        outputPath=resolved_output_path if success else None,
        cutoff=payload.cutoff,
        collapseVersion=payload.collapseVersion,
        rows=rows,
        columns=columns,
        columnNames=column_names,
        preview=preview,
        logs=logs,
        error=error,
    )
