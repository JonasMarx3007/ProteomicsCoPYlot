"""A coverage total is the union of its bars, not the row count of the matrix.

Identification and quantification are different things. A phosphosite can carry a
real peptide sequence, a localization score and a protein assignment while no
quantity survives in any run -- below threshold, interference, filtered upstream.
The shipped HEK293 phosphosite file holds 21 such rows (two of them Class I),
and the phosphoprotein file one.

The per-sample bars count quantifications. The "All samples" total counted matrix
rows, so it counted identifications, and the chart put two different quantities
on one axis: a total 21 higher than the union of the bars beneath it, disagreeing
with the missing-value plot, which already excludes never-quantified features.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]

from app.main import app
from app.services.annotation_store import get_annotation
from app.services.table_functions import prepare_coverage_df
from app.services.viewer_bootstrap import load_viewer_state

KINDS = ("protein", "phospho", "phosprot")
TOTAL = "All samples"
UNQUANTIFIED = "Identified, not quantified"


def _coverage(client, kind: str) -> pd.DataFrame:
    response = client.get(f"/api/plots/qc/{kind}/coverage-table")
    assert response.status_code == 200, response.text[:200]
    return pd.DataFrame(response.json()["rows"])


def _matrix(kind: str) -> tuple[pd.DataFrame, list[str]]:
    annotation = get_annotation(kind)
    columns = [
        s for s in annotation.metadata["sample"].astype(str)
        if s in annotation.source_data.columns
    ]
    return annotation.source_data, columns


@pytest.mark.parametrize("kind", KINDS)
def test_the_total_is_the_union_of_the_per_sample_counts(client, kind: str) -> None:
    rows = _coverage(client, kind)
    frame, columns = _matrix(kind)
    observed = frame[columns].apply(pd.to_numeric, errors="coerce").notna()
    union = int(observed.any(axis=1).sum())

    total = int(rows.loc[rows["Sample"] == TOTAL, "Number"].iloc[0])
    assert total == union, (
        f"{kind}: the total reads {total} but only {union} features are quantified "
        f"in any sample (the matrix has {len(frame)} rows)"
    )


@pytest.mark.parametrize("kind", KINDS)
def test_no_bar_can_exceed_the_total(client, kind: str) -> None:
    """The arithmetic a reader does in their head has to hold."""
    rows = _coverage(client, kind)
    bars = rows[~rows["Sample"].astype(str).isin({TOTAL, UNQUANTIFIED})]
    total = int(rows.loc[rows["Sample"] == TOTAL, "Number"].iloc[0])
    assert len(bars) > 1
    assert int(bars["Number"].max()) <= total


@pytest.mark.parametrize("kind", KINDS)
def test_identified_but_unquantified_features_are_counted_not_dropped(
    client, kind: str
) -> None:
    """Two of the phospho ones are confidently localized; losing them silently
    would trade one wrong number for a quiet omission."""
    rows = _coverage(client, kind)
    frame, columns = _matrix(kind)
    observed = frame[columns].apply(pd.to_numeric, errors="coerce").notna()
    expected = int(len(frame) - observed.any(axis=1).sum())

    stated = rows.loc[rows["Sample"] == UNQUANTIFIED, "Number"]
    if expected == 0:
        assert stated.empty, f"{kind} has none, so the row should not appear"
    else:
        assert not stated.empty, f"{kind} has {expected} but the table says nothing"
        assert int(stated.iloc[0]) == expected
        total = int(rows.loc[rows["Sample"] == TOTAL, "Number"].iloc[0])
        assert total + expected == len(frame), "the two numbers must account for every row"


def test_the_shipped_phosphosite_file_still_has_the_rows_this_is_about(example_project) -> None:
    """If the example data changes, this test should say so rather than pass vacuously."""
    frame, columns = _matrix("phospho")
    observed = frame[columns].apply(pd.to_numeric, errors="coerce").notna()
    unquantified = frame.loc[~observed.any(axis=1)]
    assert len(unquantified) == 21, (
        f"the example file now has {len(unquantified)} identified-but-unquantified "
        "phosphosites; the coverage tests above lose their teeth if this reaches 0"
    )
    assert unquantified["PTM_Collapse_key"].notna().all(), "they are real identifications"
    assert (
        pd.to_numeric(unquantified["PTM_localization"], errors="coerce") >= 0.75
    ).sum() == 2, "two are Class I, which is why they are reported rather than dropped"


# --- the plot's reference line agrees with its own bars ----------------------


@pytest.mark.parametrize("kind", KINDS)
def test_the_reference_line_matches_the_total(kind: str, example_project) -> None:
    from app.services.plot_images import _feature_context

    frame, columns = _matrix(kind)
    _, _, reference, _ = _feature_context(frame, columns)
    observed = frame[columns].apply(pd.to_numeric, errors="coerce").notna()
    assert reference == int(observed.any(axis=1).sum())


def test_the_reference_line_is_absent_rather_than_wrong_without_samples(example_project) -> None:
    """No annotated columns means no union to draw; a row count would be a guess."""
    from app.services.plot_images import _feature_context

    frame, _ = _matrix("protein")
    _, _, reference, workflow = _feature_context(frame, [])
    assert reference is None
    assert workflow == "Protein", "the workflow name must survive; only the count is unknown"


# --- the rule, on data built to break it -------------------------------------


def test_a_matrix_where_every_feature_is_unquantified() -> None:
    frame = pd.DataFrame(
        {
            "ProteinNames": [f"P{i}" for i in range(5)],
            "A_1": [np.nan] * 5,
            "A_2": [np.nan] * 5,
        }
    )
    meta = pd.DataFrame({"sample": ["A_1", "A_2"], "condition": ["A", "A"]})
    rows = prepare_coverage_df(frame, meta)
    assert int(rows.loc[rows["Sample"] == TOTAL, "Number"].iloc[0]) == 0
    assert int(rows.loc[rows["Sample"] == UNQUANTIFIED, "Number"].iloc[0]) == 5


def test_a_matrix_where_every_feature_is_quantified_says_nothing_extra() -> None:
    frame = pd.DataFrame(
        {"ProteinNames": ["P0", "P1"], "A_1": [1.0, 2.0], "A_2": [np.nan, 3.0]}
    )
    meta = pd.DataFrame({"sample": ["A_1", "A_2"], "condition": ["A", "A"]})
    rows = prepare_coverage_df(frame, meta)
    assert int(rows.loc[rows["Sample"] == TOTAL, "Number"].iloc[0]) == 2
    assert rows.loc[rows["Sample"] == UNQUANTIFIED].empty


def test_a_feature_seen_in_exactly_one_sample_counts_once() -> None:
    frame = pd.DataFrame(
        {
            "ProteinNames": ["P0", "P1", "P2"],
            "A_1": [1.0, np.nan, np.nan],
            "A_2": [np.nan, 2.0, np.nan],
        }
    )
    meta = pd.DataFrame({"sample": ["A_1", "A_2"], "condition": ["A", "A"]})
    rows = prepare_coverage_df(frame, meta)
    assert int(rows.loc[rows["Sample"] == TOTAL, "Number"].iloc[0]) == 2
    assert int(rows.loc[rows["Sample"] == UNQUANTIFIED, "Number"].iloc[0]) == 1
