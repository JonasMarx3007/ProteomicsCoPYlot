"""Rows the volcano cannot test are counted and listed, not dropped silently.

A row needs at least two values in every compared condition for the t-test.
The rest used to leave the volcano without a trace; on the bundled data that is
55 of 7,490 proteins and 1,753 of 11,916 phosphosites, mostly on/off cases. The
volcano result now carries a warning with the count and the rows themselves
(identifiers, value count and mean per condition, reason). The statistics of
the tested rows are unchanged.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.stats import VolcanoRequest
from app.services import stats_tools

ROOT = Path(__file__).resolve().parents[3]
SAMPLES = ["A1", "A2", "A3", "B1", "B2", "B3", "C1", "C2", "D1", "D2"]


def _frame() -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(2)
    frame = pd.DataFrame(rng.normal(20, 1, (8, len(SAMPLES))), columns=SAMPLES)
    frame.insert(0, "ProteinNames", [f"P{i}" for i in range(8)])
    frame.insert(1, "GeneNames", [f"G{i}" for i in range(8)])
    frame.loc[0, ["A2", "A3"]] = np.nan            # one value in A
    frame.loc[1, ["B1", "B2", "B3"]] = np.nan      # none in B
    frame.loc[2, ["A1", "A2", "B1", "B2"]] = np.nan  # one in each
    frame.loc[3, ["C1"]] = np.nan                  # one in control C
    meta = pd.DataFrame({"sample": SAMPLES, "condition": [s[0] for s in SAMPLES]})
    return frame, meta


def _run(frame, meta, untested=None, **controls):
    return stats_tools._volcano_dataframe(
        kind="protein", condition1="A", condition2="B", identifier="workflow",
        p_value_threshold=0.05, log2fc_threshold=1.0, test_type="unpaired", use_uncorrected=False,
        frame_override=frame, metadata_override=meta, untested_out=untested, **controls)


def test_untested_rows_are_listed_with_counts_means_and_reason():
    frame, meta = _frame()
    untested: list[pd.DataFrame] = []
    _, _, tested, warnings = _run(frame, meta, untested)
    rows = untested[0].set_index("ProteinNames")
    assert rows.index.tolist() == ["P0", "P1", "P2"]
    assert len(warnings) == 1 and warnings[0].startswith("3 of 8 rows were not tested")
    assert "paired" not in warnings[0] and "complete pairs" not in warnings[0]
    assert rows.loc["P0", ["n_A", "n_B"]].tolist() == [1, 3]
    assert rows.loc["P0", "mean_A"] == pytest.approx(frame.loc[0, "A1"])
    assert rows.loc["P0", "mean_B"] == pytest.approx(frame.loc[0, ["B1", "B2", "B3"]].mean())
    assert np.isnan(rows.loc["P1", "mean_B"]) and rows.loc["P1", "n_B"] == 0
    assert rows["reason"].tolist() == ["fewer than 2 values in A", "fewer than 2 values in B",
                                       "fewer than 2 values in A, B"]
    assert rows.loc["P0", "GeneNames"] == "G0"
    assert not set(SAMPLES) & set(rows.columns)
    # Tested and untested rows partition the input.
    assert sorted(tested["ProteinNames"].tolist() + rows.index.tolist()) == sorted(frame["ProteinNames"])


def test_tested_rows_are_unchanged_by_listing_the_untested_ones():
    frame, meta = _frame()
    _, _, without, _ = _run(frame, meta)
    _, _, with_list, _ = _run(frame, meta, [])
    pd.testing.assert_frame_equal(without, with_list)


def test_incomplete_pairs_are_accounted_for_even_with_two_values_per_condition():
    samples = ['A1', 'A2', 'A3', 'B1', 'B2', 'B3']
    frame = pd.DataFrame([[1, 2, 3, 4, 6, 8], [1, 2, np.nan, np.nan, 4, 5]], columns=samples)
    frame.insert(0, 'ProteinNames', ['tested', 'one_pair'])
    meta = pd.DataFrame({'sample': samples, 'condition': list('AAABBB'), 'pair_id': [1, 2, 3, 1, 2, 3]})
    excluded = []
    _, _, tested, warnings = stats_tools._volcano_dataframe(
        kind='protein', condition1='A', condition2='B', identifier='workflow',
        p_value_threshold=0.05, log2fc_threshold=1, test_type='paired', use_uncorrected=False,
        frame_override=frame, metadata_override=meta, untested_out=excluded)
    assert tested['ProteinNames'].tolist() == ['tested']
    assert excluded[0]['ProteinNames'].tolist() == ['one_pair']
    assert excluded[0]['n_pairs'].tolist() == [1]
    assert excluded[0]['reason'].tolist() == ['fewer than 2 complete pairs']
    assert warnings and 'complete pairs' in warnings[0]


def test_control_conditions_count_too_and_means_are_before_correction():
    frame, meta = _frame()
    untested: list[pd.DataFrame] = []
    _run(frame, meta, untested, condition1_control="C", condition2_control="D")
    rows = untested[0].set_index("ProteinNames")
    assert rows.loc["P3", "reason"] == "fewer than 2 values in C"
    assert rows.loc["P3", ["n_A", "n_B", "n_C", "n_D"]].tolist() == [3, 3, 1, 2]
    assert rows.loc["P3", "mean_A"] == pytest.approx(frame.loc[3, ["A1", "A2", "A3"]].mean())


def test_nothing_is_added_when_every_row_is_testable():
    frame, meta = _frame()
    frame = frame.iloc[4:].reset_index(drop=True)
    untested: list[pd.DataFrame] = []
    _, _, _, warnings = _run(frame, meta, untested)
    assert warnings == [] and untested[0].empty




@pytest.mark.parametrize("kind,total,untested", [("protein", 7490, 55), ("phospho", 11916, 1753)])
def test_bundled_data_through_the_route_the_page_calls(example_project, kind, total, untested):
    with TestClient(app) as client:
        response = client.post("/api/stats/volcano/run",
                               json=VolcanoRequest(kind=kind, condition1="GRK", condition2="WT").model_dump())
    assert response.status_code == 200, response.text[:300]
    body = response.json()
    assert len(body["untestedRows"]) == untested
    assert body["totalRows"] + untested == total
    assert f"{untested:,} of {total:,} rows were not tested" in " ".join(body["warnings"])
    assert {"n_GRK", "n_WT", "mean_GRK", "mean_WT", "reason"} <= set(body["untestedRows"][0])
