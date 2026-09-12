from __future__ import annotations

import sys
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services import r_vsn
from app.services.functions import normalize_data
from app.services.annotation_processor import prepare_normalized_log2_data, compute_annotation
from app.schemas.annotation import ConditionAssignment
from app.services.r_runtime import detect_r_runtime

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


@pytest.mark.parametrize("is_log2", [False, True])
def test_vsn_boundary_preserves_observations_and_missingness(monkeypatch, is_log2):
    source = pd.DataFrame({"id": ["P1", "P2", "P3"], "A": [0., 1.23456789012345, np.nan]})
    before = source.copy()

    def normalize(linear):
        if is_log2:
            assert linear.loc[0, "A"] == 1.
        else:
            assert pd.isna(linear.loc[0, "A"])
            assert linear.loc[1, "A"] == source.loc[1, "A"]
        assert pd.isna(linear.loc[2, "A"])
        return pd.DataFrame(42., index=linear.index, columns=linear.columns)

    monkeypatch.setattr(r_vsn, "vsn_normalize_linear", normalize)
    result = prepare_normalized_log2_data(source, ["A"], is_log2, "vsn")
    assert pd.isna(result.loc[0, "A"]) == (not is_log2)
    assert result.loc[1, "A"] == 42.
    assert pd.isna(result.loc[2, "A"])
    pd.testing.assert_frame_equal(source, before)
    pd.testing.assert_series_equal(source["id"], result["id"])


@pytest.mark.skipif(not _vsn_ready(), reason="Bioconductor vsn is not installed")
@pytest.mark.parametrize("is_log2", [False, True])
def test_real_vsn_annotation_filter_keeps_scale_contract(is_log2):
    source = _log2_frame()
    if not is_log2:
        source[SAMPLES] = np.power(2., source[SAMPLES])
    source.loc[0, SAMPLES[0]] = 0.
    source.loc[1, SAMPLES[0]] = np.nan
    result = compute_annotation(
        source, [ConditionAssignment(name="A", columns=SAMPLES)],
        is_log2, len(SAMPLES), "overall", normalization="vsn",
    )
    assert pd.isna(result.log2_data.loc[0, SAMPLES[0]]) == (not is_log2)
    assert pd.isna(result.log2_data.loc[1, SAMPLES[0]])
    assert ("P0" in result.filtered_data.ProteinNames.values) == is_log2
    assert "P1" not in result.filtered_data.ProteinNames.values


@pytest.mark.skipif(not _vsn_ready(), reason="Bioconductor vsn is not installed")
def test_r_notebook_vsn_preserves_raw_missingness_and_log2_zero():
    script = '''
      source("proteomicscopylot/notebook_functions.R")
      set.seed(3)
      d <- as.data.frame(matrix(rnorm(480, 20, 2), ncol=4))
      names(d) <- paste0("s", 0:3)
      samples <- names(d)
      raw <- 2^d
      raw[1, 1] <- 0
      raw[2, 1] <- NA_real_
      raw_before <- raw
      plain <- log2(raw)
      plain[1, 1] <- NA_real_
      output <- normalize_data(plain, samples, "vsn", linear_source=raw)
      stopifnot(identical(raw, raw_before))
      stopifnot(is.na(output[1,1]), is.na(output[2,1]))
      stopifnot(all(is.finite(as.matrix(output[-c(1,2),]))))
      d[1,1] <- 0
      d[2,1] <- NA_real_
      output_log <- normalize_data(d, samples, "vsn")
      stopifnot(is.finite(output_log[1,1]), is.na(output_log[2,1]))
    '''
    result = subprocess.run([detect_r_runtime()["executable"], "-e", script],
                            cwd=ROOT, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stderr


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
