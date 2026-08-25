from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.schemas.external import PeptideCollapseRequest
from app.services.external_functions import (
    peptideCollapse,
    peptideCollapse_fixed,
    peptideCollapse_old,
    process_and_export,
)
from app.services.external_tools import COLLAPSE_VERSIONS

RUNS = ["run1", "run2"]
PEPTIDES = [
    ("SAMPLE[Phospho (STY)]PEPTIDEK", "P00001", "GENEA", 10),
    ("ANOTHER[Phospho (STY)]PEPTIDER", "P00002", "GENEB", 20),
    ("THIRDPEP[Phospho (STY)]TIDEK", "P00003", "GENEC", 30),
]


def _table(run2_first) -> pd.DataFrame:
    quantities = {"run1": [1000.0, 2000.0, 4000.0], "run2": [run2_first, 2000.0, 4000.0]}
    rows = []
    for run in RUNS:
        for (seq, protein, gene, position), quantity in zip(PEPTIDES, quantities[run]):
            rows.append(
                {
                    "R.FileName": run,
                    "EG.PrecursorId": f"_{seq}_.2",
                    "EG.TotalQuantity (Settings)": quantity,
                    "PEP.PeptidePosition": str(position),
                    "EG.PTMAssayProbability": 0.99,
                    "PG.Genes": gene,
                    "PG.ProteinGroups": protein,
                }
            )
    return pd.DataFrame(rows)


def _collapse(func, table: pd.DataFrame) -> pd.DataFrame:
    with contextlib.redirect_stdout(io.StringIO()):
        return func(table.copy(), cutoff=0.0)


def _quantities(frame: pd.DataFrame) -> np.ndarray:
    columns = [c for c in frame.columns if any(run in str(c) for run in RUNS)]
    return frame[columns].to_numpy(dtype=float, na_value=np.nan).ravel()


def test_the_missing_value_sentinel_becomes_nan_not_negative_infinity() -> None:
    values = _quantities(_collapse(peptideCollapse_fixed, _table(0.0)))
    assert not np.isinf(values).any(), (
        "log2(0) leaked through as -inf; filter_data counts -inf as an observation, "
        "so the row survives filtering and then yields an infinite fold change"
    )
    assert np.isnan(values).sum() == 1


def test_a_genuine_intensity_of_one_is_not_deleted() -> None:
    values = _quantities(_collapse(peptideCollapse_fixed, _table(1.0)))
    assert not np.isnan(values).any(), "a real measurement of 1.0 was dropped as if it were a sentinel"
    assert 0.0 in [round(float(v), 6) for v in values]


def test_a_filtered_cell_does_not_crash_the_collapse() -> None:
    values = _quantities(_collapse(peptideCollapse_fixed, _table("Filtered")))
    assert np.isnan(values).sum() == 1
    assert not np.isinf(values).any()


def test_clean_data_is_unchanged_by_the_fix() -> None:
    table = _table(1500.0)
    before = _quantities(_collapse(peptideCollapse, table))
    after = _quantities(_collapse(peptideCollapse_fixed, table))
    assert np.array_equal(before, after, equal_nan=True), (
        "the fixed variant must be inert on data that carries no sentinels"
    )


@pytest.mark.parametrize("bad", [0.0, "Filtered"])
def test_the_older_variants_still_show_the_defect_they_are_kept_for(bad) -> None:
    try:
        values = _quantities(_collapse(peptideCollapse, _table(bad)))
    except TypeError:
        return
    assert np.isinf(values).any() or np.isnan(values).sum() == 0


def test_every_selectable_version_maps_to_a_distinct_implementation() -> None:
    assert COLLAPSE_VERSIONS == {
        "fixed": peptideCollapse_fixed,
        "newest": peptideCollapse,
        "legacy": peptideCollapse_old,
    }
    assert len(set(COLLAPSE_VERSIONS.values())) == 3


def test_the_fixed_variant_is_the_default_everywhere() -> None:
    assert PeptideCollapseRequest(inputPath="x.tsv").collapseVersion == "fixed"
    assert COLLAPSE_VERSIONS["fixed"] is peptideCollapse_fixed
    import inspect

    default = inspect.signature(process_and_export).parameters["collapse_func"].default
    assert default is peptideCollapse_fixed


def test_the_fixed_variant_keeps_every_site_by_default() -> None:
    import inspect

    default = inspect.signature(peptideCollapse_fixed).parameters["cutoff"].default
    assert default == 0.0, (
        "peptideCollapse_fixed must default to cutoff 0.0. The schema, the API and "
        "the UI all pass 0, so a 0.75 in the signature would never take effect and "
        "would misdescribe what the function does"
    )
    assert PeptideCollapseRequest(inputPath="x.tsv").cutoff == 0.0
    assert inspect.signature(process_and_export).parameters["cutoff"].default == 0


def test_an_explicit_class_one_cutoff_still_filters() -> None:
    table = _table(1500.0)
    everything = _collapse(peptideCollapse_fixed, table)
    with contextlib.redirect_stdout(io.StringIO()):
        class_one = peptideCollapse_fixed(table.copy(), cutoff=0.75)
    assert len(class_one) <= len(everything)


def test_an_unknown_version_is_rejected_rather_than_defaulted() -> None:
    with pytest.raises(Exception):
        PeptideCollapseRequest(inputPath="x.tsv", collapseVersion="not_a_version")
