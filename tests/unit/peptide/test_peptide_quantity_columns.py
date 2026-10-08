"""Which peptide quantity column completeness reads.

Split out of test_small_bugs.py (2026-10-02)."""
from __future__ import annotations

import pandas as pd
import pytest

from app.services.peptide_quantity import resolve_peptide_quantity_column as _peptide_quantity_column


@pytest.mark.parametrize(
    "column",
    ["Precursor.Quantity", "PG.Quantity", "Intensity", "LFQ intensity", "Abundance", "iBAQ"],
)
def test_recognised_quantity_columns_are_found(column: str) -> None:
    frame = pd.DataFrame({"Charge": [2, 3], "RT": [10.1, 12.4], column: [1.0, 2.0]})
    assert _peptide_quantity_column(frame) == column


def test_precursor_quantity_wins_over_other_candidates() -> None:
    frame = pd.DataFrame({"Intensity": [1.0], "Precursor.Quantity": [2.0]})
    assert _peptide_quantity_column(frame) == "Precursor.Quantity"


def test_missing_quantity_column_raises_instead_of_using_retention_time() -> None:
    frame = pd.DataFrame({"Charge": [2, 3], "RT": [10.1, 12.4], "Q.Value": [0.001, 0.004]})
    with pytest.raises(ValueError) as excinfo:
        _peptide_quantity_column(frame)
    message = str(excinfo.value)
    assert "Precursor.Quantity" in message
    assert "Charge" in message, "the error should list what was actually found"
