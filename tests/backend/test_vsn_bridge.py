from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services import r_vsn
from app.services.functions import normalize_data

SAMPLES = [f"s{i}" for i in range(4)]


def _log2_frame(n: int = 120) -> pd.DataFrame:
    rng = np.random.default_rng(3)
    values = rng.normal(20.0, 2.0, (n, len(SAMPLES))) + np.array([0.0, 1.1, -0.8, 0.5])
    frame = pd.DataFrame(values, columns=SAMPLES)
    frame.insert(0, "ProteinNames", [f"P{i}" for i in range(n)])
    return frame


def _vsn_ready() -> bool:
    try:
        return bool(r_vsn.vsn_availability().get("available"))
    except Exception:
        return False


@pytest.fixture(scope="module")
def vsn_default():
    return normalize_data(_log2_frame(), SAMPLES, "vsn")


def test_availability_report_is_self_consistent() -> None:
    info = r_vsn.vsn_availability()
    assert set(info) >= {"available", "rAvailable", "packageInstalled"}
    if info["available"]:
        assert info["rAvailable"] and info["packageInstalled"]
        assert info.get("reason") is None
    else:
        assert str(info.get("reason") or "").strip()


def test_unavailable_vsn_raises_an_actionable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        r_vsn,
        "vsn_availability",
        lambda: {
            "available": False,
            "rAvailable": False,
            "packageInstalled": False,
            "reason": "Rscript was not found.",
        },
    )
    with pytest.raises(ValueError) as excinfo:
        r_vsn.vsn_normalize_linear(pd.DataFrame({"a": [1.0, 2.0]}))
    assert "Rscript" in str(excinfo.value)


def test_normalize_data_surfaces_the_reason_rather_than_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        r_vsn,
        "vsn_availability",
        lambda: {"available": False, "reason": "vsn package is not installed."},
    )
    with pytest.raises(ValueError) as excinfo:
        normalize_data(_log2_frame(20), SAMPLES, "vsn")
    assert "vsn" in str(excinfo.value).lower()


@pytest.mark.skipif(not _vsn_ready(), reason="Bioconductor vsn is not installed")
def test_vsn_round_trip_preserves_shape_and_labels(vsn_default) -> None:
    frame = _log2_frame()
    out = vsn_default
    assert list(out.columns) == list(frame.columns)
    assert len(out) == len(frame)
    pd.testing.assert_series_equal(out["ProteinNames"], frame["ProteinNames"])
    assert np.isfinite(out[SAMPLES].to_numpy()).all()


@pytest.mark.skipif(not _vsn_ready(), reason="Bioconductor vsn is not installed")
def test_vsn_preserves_the_missing_value_pattern() -> None:
    rng = np.random.default_rng(11)
    frame = _log2_frame()
    holes = rng.random((len(frame), len(SAMPLES))) < 0.15
    for index, column in enumerate(SAMPLES):
        frame.loc[holes[:, index], column] = np.nan
    out = normalize_data(frame, SAMPLES, "vsn")
    assert np.array_equal(frame[SAMPLES].isna().to_numpy(), out[SAMPLES].isna().to_numpy())


@pytest.mark.skipif(not _vsn_ready(), reason="Bioconductor vsn is not installed")
def test_vsn_reduces_between_sample_spread(vsn_default) -> None:
    frame = _log2_frame()
    before = frame[SAMPLES].median().to_numpy().std()
    after = vsn_default[SAMPLES].median().to_numpy().std()
    assert before > 0.5, "fixture should carry a real loading offset"
    assert after < before / 4.0


@pytest.mark.skipif(not _vsn_ready(), reason="Bioconductor vsn is not installed")
def test_vsn_is_deterministic() -> None:
    frame = _log2_frame()
    first = normalize_data(frame, SAMPLES, "vsn")[SAMPLES].to_numpy()
    second = normalize_data(frame, SAMPLES, "vsn")[SAMPLES].to_numpy()
    assert np.allclose(first, second, atol=0, rtol=0)


@pytest.mark.skipif(not _vsn_ready(), reason="Bioconductor vsn is not installed")
def test_linear_source_is_used_verbatim_when_supplied(vsn_default) -> None:
    frame = _log2_frame()
    linear = pd.DataFrame(
        np.power(2.0, frame[SAMPLES].to_numpy()), columns=SAMPLES, index=frame.index
    )
    with_source = normalize_data(frame, SAMPLES, "vsn", linear_source=linear)[SAMPLES]
    without = vsn_default[SAMPLES]
    assert with_source.shape == without.shape
    assert list(with_source.columns) == SAMPLES
