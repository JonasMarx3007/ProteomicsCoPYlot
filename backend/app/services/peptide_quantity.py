from __future__ import annotations

import re

import numpy as np
import pandas as pd


_ABUNDANCE_TOKENS = {"quantity", "intensity", "abundance", "area", "lfq", "ibaq"}
_NON_ABUNDANCE_COMPACT = ("qvalue", "charge", "retentiontime")
_NON_ABUNDANCE_TOKENS = {"cv", "error", "mz", "qvalue", "rank", "score", "sd", "se", "stderr", "stdev"}


def peptide_quantity_columns(frame: pd.DataFrame) -> list[str]:
    """Return credible peptide abundance columns in source-column order.

    Column names are intentionally the only automatic signal. Numeric dtype is
    not sufficient: common peptide reports also contain numeric charge, m/z,
    retention-time and q-value columns.
    """
    candidates: list[str] = []
    for raw_column in frame.columns:
        column = str(raw_column)
        normalized = column.strip().lower()
        compact = re.sub(r"[^a-z0-9]+", "", normalized)
        words = set(re.findall(r"[a-z0-9]+", normalized))
        if any(pattern in compact for pattern in _NON_ABUNDANCE_COMPACT):
            continue
        if words.intersection(_NON_ABUNDANCE_TOKENS):
            continue
        if not (words.intersection(_ABUNDANCE_TOKENS) or "ibaq" in compact or "lfq" in compact):
            continue
        numeric = pd.to_numeric(frame[raw_column], errors="coerce")
        if bool(np.isfinite(numeric.to_numpy(dtype=float, na_value=np.nan)).any()):
            candidates.append(column)
    return candidates


def default_peptide_quantity_column(frame: pd.DataFrame) -> str | None:
    """Return an unambiguous automatic choice, otherwise ``None``."""
    candidates = peptide_quantity_columns(frame)
    canonical = next(
        (column for column in candidates if column.strip().lower() == "precursor.quantity"),
        None,
    )
    if canonical is not None:
        return canonical
    if len(candidates) == 1:
        return candidates[0]
    return None


def resolve_peptide_quantity_column(
    frame: pd.DataFrame,
    requested: str | None = None,
) -> str:
    """Resolve a peptide abundance column without guessing from numeric data."""
    candidates = peptide_quantity_columns(frame)
    requested_normalized = str(requested or "").strip()
    if requested_normalized:
        exact = next((column for column in candidates if column == requested_normalized), None)
        if exact is None:
            available = ", ".join(candidates) or "none"
            raise ValueError(
                f"Selected peptide abundance column '{requested_normalized}' is not a supported "
                f"abundance column in this dataset. Supported columns: {available}."
            )
        return exact

    automatic = default_peptide_quantity_column(frame)
    if automatic is not None:
        return automatic
    if len(candidates) > 1:
        choices = ", ".join(candidates)
        raise ValueError(
            "Multiple peptide abundance columns are available. Select one explicitly in the "
            f"plot options. Choices: {choices}."
        )

    available = ", ".join(str(column) for column in frame.columns[:12])
    raise ValueError(
        "Peptide dataset is missing a usable abundance column. Expected a column named "
        "'Precursor.Quantity' or one containing quantity, intensity, abundance, area, LFQ, "
        f"or iBAQ. Columns found: {available}."
    )
