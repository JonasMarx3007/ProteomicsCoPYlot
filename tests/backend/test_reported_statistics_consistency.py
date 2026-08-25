from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import app.services.completeness_tools as ct

SERVICES = ROOT / "backend" / "app" / "services"


def test_ai_context_uses_the_same_ddof_as_the_statistical_paths() -> None:
    source = (SERVICES / "ai_functions.py").read_text(encoding="utf-8")
    assert "ddof=0" not in source, (
        "ai_functions computes a population sd; the statistical paths use ddof=1, "
        "so the assistant would quote a different number than the result table"
    )


@pytest.mark.parametrize("n", [3, 4, 5])
def test_the_two_conventions_really_do_differ_at_these_group_sizes(n: int) -> None:
    values = pd.Series(np.random.default_rng(n).normal(20, 1.5, n))
    assert values.std(ddof=0) < values.std(ddof=1)
    understatement = 1 - values.std(ddof=0) / values.std(ddof=1)
    assert understatement > 0.10, "expected a double-digit gap at proteomics n"


def test_pandas_default_matches_the_statistical_convention() -> None:
    values = pd.Series([1.0, 2.0, 4.0])
    assert values.std() == values.std(ddof=1)


def _peptide_frame(runs: list[str]) -> pd.DataFrame:
    rng = np.random.default_rng(3)
    rows = []
    for run in runs:
        for index in range(40):
            precursor = f"PEP{index}_2"
            base = {
                "File.Name": run,
                "Precursor.Id": precursor,
                "Stripped.Sequence": precursor.split("_")[0],
            }
            quantities = (
                [0.0, float(rng.integers(100, 1000))]
                if index % 5 == 0
                else [float(rng.integers(100, 1000)), float(rng.integers(100, 1000))]
            )
            for quantity in quantities:
                rows.append({**base, "Precursor.Quantity": quantity})
    return pd.DataFrame(rows)


RUNS = [f"run_{i}.raw" for i in (1, 2, 3, 4)]


def _render(frame: pd.DataFrame, builder) -> bytes:
    class _Annotation:
        metadata = pd.DataFrame({"sample": RUNS, "condition": ["A"] * len(RUNS)})

    with patch.object(ct, "get_annotation", return_value=_Annotation()), patch(
        "app.services.peptide_tools.get_peptide_frame", return_value=frame
    ):
        return builder(dpi=50, width_cm=6, height_cm=4)


BUILDERS = {
    "precursor": ct.completeness_missing_value_plot_precursor,
    "peptide": ct.completeness_missing_value_plot_peptide,
}


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_completeness_is_independent_of_input_row_order(name: str) -> None:
    frame = _peptide_frame(RUNS)
    reversed_rows = frame.iloc[::-1].reset_index(drop=True)
    assert _render(frame, BUILDERS[name]) == _render(reversed_rows, BUILDERS[name]), (
        f"{name} completeness changed when the input rows were reordered"
    )


def test_both_pivots_use_the_same_collapse_rule() -> None:
    source = (SERVICES / "completeness_tools.py").read_text(encoding="utf-8")
    aggfuncs = re.findall(r'aggfunc="(\w+)"', source)
    assert aggfuncs, "no pivot aggfunc found — did the pivots move?"
    assert set(aggfuncs) == {"max"}, f"mixed collapse rules: {aggfuncs}"


def test_the_unstable_rule_really_is_unstable() -> None:
    rows = [
        {"Precursor.Id": "PEP_2", "File.Name": "r1", "Precursor.Quantity": 100.0},
        {"Precursor.Id": "PEP_2", "File.Name": "r1", "Precursor.Quantity": 900.0},
    ]
    forward = pd.DataFrame(rows)
    reversed_ = pd.DataFrame(rows[::-1])

    def collapse(frame: pd.DataFrame, rule: str) -> float:
        pivot = frame.pivot_table(
            index="Precursor.Id",
            columns="File.Name",
            values="Precursor.Quantity",
            aggfunc=rule,
        )
        return float(pivot.iloc[0, 0])

    assert collapse(forward, "first") != collapse(reversed_, "first")
    assert collapse(forward, "max") == collapse(reversed_, "max")
