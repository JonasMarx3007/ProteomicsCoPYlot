"""A note under the log2 checkbox when the values look like log10, ln or count data.

The auto-detection cannot tell log2 from log10, natural-log or count data, so it
pre-ticks "already log2" for all of them; with log10 values a |log2FC| = 1
threshold then means about 10-fold. The detection is unchanged; the page shows
a note when the values look unusual for log2 intensities.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.annotation_processor import detect_log2_transformed, log2_scale_hint
from app.services.dataset_store import reset_all_datasets, save_table_dataset

ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = ROOT / "proteomicscopylot" / "example_data"
SAMPLES = ["A1", "A2", "B1", "B2"]


def _matrix(kind: str) -> pd.DataFrame:
    rng = np.random.default_rng(8)
    linear = np.power(2.0, rng.normal(22, 2, (500, len(SAMPLES))))
    values = {
        "log2": np.log2(linear),
        "log10": np.log10(linear),
        "ln": np.log(linear),
        "counts": rng.poisson(6, (500, len(SAMPLES))).astype(float),
        "log2 ratios": rng.normal(0, 1, (500, len(SAMPLES))),
    }[kind]
    frame = pd.DataFrame(values, columns=SAMPLES)
    frame.insert(0, "ProteinNames", [f"P{i}" for i in range(len(frame))])
    return frame


@pytest.mark.parametrize("kind,expected", [
    ("log10", "The values have a median of 6.6; log2 intensities are usually around 15-30."),
    ("counts", "100% of the values are whole numbers, which looks like count data"),
])
def test_values_that_look_like_another_scale_get_a_hint(kind, expected):
    hint = log2_scale_hint(_matrix(kind), SAMPLES)
    assert hint is not None and hint.startswith(expected)


def test_natural_log_intensities_are_not_caught():
    """A known limit: ln intensities (median ~15) overlap low log2 intensities.

    Lowering the bar to catch them would put the note on ordinary log2 data.
    """
    frame = _matrix("ln")
    assert 14 < float(np.median(frame[SAMPLES])) < 16
    assert log2_scale_hint(frame, SAMPLES) is None


@pytest.mark.parametrize("kind", ["log2", "log2 ratios"])
def test_ordinary_log2_intensities_and_centred_log2_ratios_get_none(kind):
    assert log2_scale_hint(_matrix(kind), SAMPLES) is None


def test_columns_named_log2_are_trusted_for_the_median_but_not_for_counts():
    frame = _matrix("log10").rename(columns={s: f"{s}.Log2Quantity" for s in SAMPLES})
    assert log2_scale_hint(frame, [f"{s}.Log2Quantity" for s in SAMPLES]) is None
    counts = _matrix("counts").rename(columns={s: f"{s}.Log2Quantity" for s in SAMPLES})
    assert log2_scale_hint(counts, [f"{s}.Log2Quantity" for s in SAMPLES]).startswith("100% of the values")


def test_the_detection_itself_is_unchanged():
    # The scale guess still says log2 for log10 data; the hint is what changed.
    assert detect_log2_transformed(_matrix("log10"), SAMPLES).is_log2_transformed is True


@pytest.mark.parametrize("data_file,meta_file,expected", [
    ("20260511_144120_20240822_JM_HEK293_WP_Report_PG.tsv", "protein_metadata_full.csv", None),
    ("20260511_144129_20240822_JM_HEK293_PP_Report_collapsed.tsv", "phospho_metadata_full.csv",
     "The values have a median of 3.9"),
])
def test_the_bundled_examples(data_file, meta_file, expected):
    frame = pd.read_csv(EXAMPLE / data_file, sep="\t")
    samples = pd.read_csv(EXAMPLE / meta_file)["sample"].astype(str).tolist()
    hint = log2_scale_hint(frame, samples)
    assert hint == expected if expected is None else hint.startswith(expected)


def test_the_detect_route_returns_the_hint():
    reset_all_datasets()
    save_table_dataset("log10.tsv", "protein", _matrix("log10"))
    with TestClient(app) as client:
        response = client.post("/api/annotations/log2-detect", json={"kind": "protein", "sampleColumns": SAMPLES})
    assert response.status_code == 200, response.text[:300]
    body = response.json()
    assert body["isLog2Transformed"] is True
    assert body["scaleHint"].startswith("The values have a median of 6.6")
