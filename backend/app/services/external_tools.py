from __future__ import annotations

import os

import pandas as pd

from app.schemas.external import PeptideCollapseRequest, PeptideCollapseResponse
from app.services.external_functions import process_and_export


def _normalize_path(path: str) -> str:
    return path.strip().strip('"').strip("'")


def _resolve_output_path(input_path: str, output_path: str | None) -> str:
    if output_path:
        return output_path
    base_name, _ = os.path.splitext(input_path)
    return f"{base_name}_collapsed.tsv"


def run_peptide_collapse(payload: PeptideCollapseRequest) -> PeptideCollapseResponse:
    input_path = _normalize_path(payload.inputPath)
    output_path = _normalize_path(payload.outputPath) if payload.outputPath else None

    if not input_path:
        raise ValueError("Input file path is required.")
    if not os.path.exists(input_path):
        raise ValueError(f"Input file not found: {input_path}")

    resolved_output_path = _resolve_output_path(input_path, output_path)

    messages: list[str] = []
    frame = process_and_export(
        input_path,
        output_path=resolved_output_path,
        cutoff=payload.cutoff,
        progress=messages.append,
    )
    preview_frame = frame.head(30).astype(object).where(pd.notna(frame.head(30)), None)

    return PeptideCollapseResponse(
        success=True,
        inputPath=input_path,
        outputPath=resolved_output_path,
        cutoff=payload.cutoff,
        rows=len(frame),
        columns=len(frame.columns),
        columnNames=[str(column) for column in frame.columns],
        preview=preview_frame.to_dict(orient="records"),
        logs="\n".join(messages),
        error=None,
    )
