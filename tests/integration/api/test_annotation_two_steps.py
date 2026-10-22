"""Filtering and normalization are two steps, in that order.

Since 2026-10-20 the annotation page applies the valid-value filter first and
the normalization afterwards, and the normalization is fitted on the rows the
filter kept and applied to every row (fitting on every row
let the low-abundance rows a filter removes shift unchanged proteins by up to
0.5 log2 units). `/generate` is the filter step and `/normalize` the second;
"none" takes a normalization away again.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.annotation_store import get_annotation
from app.services.functions import filter_data, normalize_data


def _table(rows: int = 1500, seed: int = 3) -> bytes:
    rng = np.random.default_rng(seed)
    base = rng.normal(24, 2, rows)
    frame = pd.DataFrame({f"{c}{i}": base + rng.normal(0, 0.3, rows) for c in "AB" for i in (1, 2, 3)})
    # Condition B misses its low values far more often than A.
    for column in ("B1", "B2", "B3"):
        drop = rng.random(rows) < 1 / (1 + np.exp((frame[column] - 22.5) / 0.7))
        frame.loc[drop, column] = np.nan
    for column in ("A1", "A2", "A3"):
        drop = rng.random(rows) < 1 / (1 + np.exp((frame[column] - 20.5) / 0.7))
        frame.loc[drop, column] = np.nan
    frame.insert(0, "ProteinNames", [f"P{k}" for k in range(rows)])
    return frame.to_csv(index=False).encode()


CONDITIONS = [{"name": "A", "columns": ["A1", "A2", "A3"]}, {"name": "B", "columns": ["B1", "B2", "B3"]}]
FILTER = {"method": "at_least_n", "minPresent": 3, "minPercentage": 70, "mode": "per_group", "normalization": "none"}


@pytest.fixture
def client():
    with TestClient(app) as client:
        assert client.post("/api/datasets/upload", data={"kind": "protein"},
                           files={"file": ("t.csv", _table())}).status_code == 200
        yield client


def _generate(client: TestClient, **filter_updates):
    response = client.post("/api/annotations/generate", json={
        "kind": "protein", "conditions": CONDITIONS, "isLog2Transformed": True,
        "filter": {**FILTER, **filter_updates}})
    assert response.status_code == 200, response.text
    return response.json()


def test_filter_first_then_normalize_fits_on_the_kept_rows(client) -> None:
    filtered_only = _generate(client)
    assert filtered_only["filter"]["normalization"] == "none"
    plain = get_annotation("protein")
    rows_kept = len(plain.filtered_data)
    assert 0 < rows_kept < len(plain.log2_data)

    normalized = client.post("/api/annotations/normalize", json={"kind": "protein", "normalization": "median"})
    assert normalized.status_code == 200, normalized.text
    assert normalized.json()["filter"]["normalization"] == "median"
    assert normalized.json()["filteredRows"] == rows_kept, "normalizing never changes which rows the filter kept"
    stored = get_annotation("protein")
    samples = stored.metadata["sample"].tolist()

    # The filtered matrix is exactly a median centring of the kept rows alone ...
    expected = normalize_data(plain.filtered_data, samples, "median")
    pd.testing.assert_frame_equal(stored.filtered_data[samples], expected[samples])
    # ... and not a centring of every row, which the old order produced.
    old_order = filter_data(normalize_data(plain.log2_data, samples, "median"), stored.metadata, 3, "per_group")
    assert not np.allclose(stored.filtered_data[samples].to_numpy(), old_order[samples].to_numpy(), equal_nan=True)
    # The unfiltered matrix carries the same shift (one scale for QC and statistics).
    shift = (stored.log2_data[samples] - plain.log2_data[samples]).dropna(how="all")
    assert np.allclose(shift.std(axis=0).fillna(0), 0, atol=1e-9)
    assert any("fitted on the rows the valid-value filter kept" in w for w in stored.warnings)


def test_none_takes_the_normalization_away_again(client) -> None:
    _generate(client)
    before = get_annotation("protein").filtered_data.copy()
    assert client.post("/api/annotations/normalize", json={"kind": "protein", "normalization": "quantile"}).status_code == 200
    assert not before.equals(get_annotation("protein").filtered_data)
    assert client.post("/api/annotations/normalize", json={"kind": "protein", "normalization": "none"}).status_code == 200
    pd.testing.assert_frame_equal(get_annotation("protein").filtered_data, before)
    assert get_annotation("protein").filter_config.normalization == "none"


def test_normalize_needs_the_filter_step_first(client) -> None:
    response = client.post("/api/annotations/normalize", json={"kind": "protein", "normalization": "median"})
    assert response.status_code == 400 and "filter first" in response.json()["detail"]


def test_normalize_keeps_a_pairing_saved_after_the_filter(client) -> None:
    _generate(client)
    pairs = [{"condition1Sample": f"A{i}", "condition2Sample": f"B{i}"} for i in (1, 2, 3)]
    assert client.put("/api/annotations/pairing", json={"kind": "protein", "condition1": "A", "condition2": "B", "pairs": pairs}).status_code == 200
    ids_before = dict(zip(get_annotation("protein").metadata["sample"], get_annotation("protein").metadata["pair_id"]))
    assert client.post("/api/annotations/normalize", json={"kind": "protein", "normalization": "median"}).status_code == 200
    ids_after = dict(zip(get_annotation("protein").metadata["sample"], get_annotation("protein").metadata["pair_id"]))
    assert ids_after == ids_before


def test_a_whole_config_in_generate_still_works_for_saved_sessions_and_viewers(client) -> None:
    one_step = _generate(client, normalization="median")
    assert one_step["filter"]["normalization"] == "median"
    via_two_steps_rows = one_step["filteredRows"]
    one_step_frame = get_annotation("protein").filtered_data.copy()
    _generate(client)
    client.post("/api/annotations/normalize", json={"kind": "protein", "normalization": "median"})
    assert get_annotation("protein").filtered_data.shape[0] == via_two_steps_rows
    pd.testing.assert_frame_equal(get_annotation("protein").filtered_data, one_step_frame)


def test_a_complete_feature_fit_removes_the_missingness_shift(client) -> None:
    """The reviewer's case (M2): uneven MNAR missingness, no filter (the app default).

    Fitted on the filtered rows -- here every row -- the unchanged proteins of the
    sparser group sit far below the other group after median centring. Fitted on
    the features observed in every sample, they do not.
    """
    _generate(client, minPresent=0)
    samples = ["A1", "A2", "A3", "B1", "B2", "B3"]

    def shift() -> float:
        frame = get_annotation("protein").log2_data[samples].dropna()
        return float(frame[["B1", "B2", "B3"]].mean(axis=1).sub(frame[["A1", "A2", "A3"]].mean(axis=1)).median())

    assert client.post("/api/annotations/normalize", json={"kind": "protein", "normalization": "median"}).status_code == 200
    assert get_annotation("protein").filter_config.normalizationFit == "filtered_rows"
    on_filtered = shift()
    response = client.post("/api/annotations/normalize",
                           json={"kind": "protein", "normalization": "median", "normalizationFit": "complete_features"})
    assert response.status_code == 200, response.text
    assert response.json()["filter"]["normalizationFit"] == "complete_features"
    on_complete = shift()
    assert abs(on_filtered) > 0.25, on_filtered
    assert abs(on_complete) < 0.05 and abs(on_complete) < abs(on_filtered) / 5, (on_filtered, on_complete)
    assert any("features observed in every sample" in w for w in get_annotation("protein").warnings)
    # The fit basis is part of the saved state and comes back with it.
    import gzip, json
    exported = client.post("/api/restore/export", json={"portable": True})
    state = json.loads(gzip.decompress(exported.content))
    entry = next(p for p in state["backend"]["packages"] if p["datasets"].get("protein"))
    annotation = next(a for a in entry["annotations"] if a.get("kind") == "protein")
    assert annotation["filter"]["normalizationFit"] == "complete_features"


@pytest.mark.parametrize("method", ["median", "quantile", "vsn"])
def test_complete_feature_fit_without_complete_rows_is_blocked(client, method) -> None:
    frame = pd.DataFrame({
        "ProteinNames": ["P1", "P2", "P3", "P4"],
        **{f"A{i}": [20., 21., np.nan, np.nan] for i in (1, 2, 3)},
        **{f"B{i}": [np.nan, np.nan, 22., 23.] for i in (1, 2, 3)},
    })
    assert client.post("/api/datasets/upload", data={"kind": "protein"},
                       files={"file": ("incomplete.csv", frame.to_csv(index=False).encode())}).status_code == 200
    _generate(client, minPresent=0, normalization="median")
    stored = get_annotation("protein")
    before = stored.log2_data.copy(deep=True)
    response = client.post("/api/annotations/normalize", json={
        "kind": "protein", "normalization": method, "normalizationFit": "complete_features"})
    assert response.status_code == 400, response.text
    assert "no feature is observed in every sample" in response.json()["detail"]
    assert "Filtered rows" in response.json()["detail"]
    assert get_annotation("protein") is stored
    pd.testing.assert_frame_equal(stored.log2_data, before)
    assert stored.filter_config.normalizationFit == "filtered_rows"
    # Turning normalization off must remain possible with this selection retained.
    response = client.post("/api/annotations/normalize", json={
        "kind": "protein", "normalization": "none", "normalizationFit": "complete_features"})
    assert response.status_code == 200, response.text
    assert get_annotation("protein").filter_config.normalization == "none"
