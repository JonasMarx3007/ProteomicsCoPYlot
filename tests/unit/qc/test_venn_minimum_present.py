"""Venn condition sets can require a feature in several replicates.

With one value enough, a feature seen in a single replicate counts as present in
that condition, which makes conditions look alike when detection is patchy.
The minimum defaults to 1 (unchanged behaviour) and only applies in Condition mode.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.annotation import AnnotationFilterConfig
from app.services.annotation_store import reset_all_annotations, save_annotation
from app.services.comparison_tools import venn_table
from app.services.dataset_store import reset_all_datasets, save_table_dataset

SAMPLES = ["A1", "A2", "A3", "B1", "B2", "B3"]


@pytest.fixture
def patchy():
    reset_all_datasets()
    reset_all_annotations()
    values = np.full((4, 6), 20.0)
    values[0, 1:3] = np.nan          # P0: one value in A
    values[1, 2] = np.nan            # P1: two values in A
    values[2, 3:6] = np.nan          # P2: none in B
    frame = pd.DataFrame(values, columns=SAMPLES)
    frame.insert(0, "ProteinNames", [f"P{i}" for i in range(4)])
    meta = pd.DataFrame({"sample": SAMPLES, "condition": [s[0] for s in SAMPLES]})
    save_table_dataset("patchy.tsv", "protein", frame)
    save_annotation(kind="protein", source_data=frame, log2_data=frame, filtered_data=frame, metadata=meta,
                    is_log2_transformed=True, metadata_source="manual", filter_config=AnnotationFilterConfig(),
                    auto_detected=False, warnings=[])
    yield
    reset_all_datasets()
    reset_all_annotations()


def _counts(**options) -> dict[str, int]:
    table = venn_table("protein", mode="Condition", first="A", second="B", **options)
    return dict(zip(table["Region"], table["Count"]))


def test_default_counts_any_replicate_as_before(patchy):
    assert _counts() == _counts(min_present=1)
    assert _counts()["Total A"] == 4 and _counts()["Total B"] == 3


@pytest.mark.parametrize("minimum,total_a", [(2, 3), (3, 2)])
def test_a_higher_minimum_drops_patchy_features(patchy, minimum, total_a):
    assert _counts(min_present=minimum)["Total A"] == total_a
    assert _counts(min_present=minimum)["Total B"] == 3


def test_routes_pass_the_minimum_and_refuse_impossible_ones(patchy):
    params = {"mode": "Condition", "first": "A", "second": "B"}
    with TestClient(app) as client:
        table = client.get("/api/plots/comparison/protein/venn-table", params={**params, "minPresent": 3}).json()
        assert {row["Region"]: row["Count"] for row in table["rows"]}["Total A"] == 2
        image = client.get("/api/plots/comparison/protein/venn.png", params={**params, "minPresent": 3})
        assert image.status_code == 200, image.text[:200]
        token = image.headers["x-copylot-notebook"]
        snapshot = client.get("/api/plots/comparison/protein/venn-table",
                              params={**params, "minPresent": 3, "snapshot": token})
        assert snapshot.json() == table
        stale = client.get("/api/plots/comparison/protein/venn-table",
                           params={**params, "minPresent": 1, "snapshot": token})
        assert stale.status_code == 409
        too_many = client.get("/api/plots/comparison/protein/venn-table", params={**params, "minPresent": 4})
        assert too_many.status_code == 400
        assert "fewer than the minimum of 4" in too_many.text


def test_single_sample_mode_ignores_it(patchy):
    single = venn_table("protein", mode="Single", first="A1", second="B1", min_present=3)
    assert dict(zip(single["Region"], single["Count"]))["Total A1"] == 4
