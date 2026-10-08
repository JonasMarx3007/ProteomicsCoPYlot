from __future__ import annotations

import inspect
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]

from app.schemas.data_tools import ImputationRunRequest
from app.services.functions import impute_values_with_diagnostics
from proteomicscopylot.notebook_functions import impute_values

WT = [f"WT_{i}" for i in range(1, 6)]
KO = [f"KO_{i}" for i in range(1, 6)]


def _offset_frame(offset: float = 1.0) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(3)
    values = rng.normal(22, 2.0, (3000, 10))
    values[:, 5:] += offset
    frame = pd.DataFrame(values, columns=WT + KO)
    frame.loc[0, "KO_1"] = np.nan
    meta = pd.DataFrame({"sample": WT + KO, "condition": ["WT"] * 5 + ["KO"] * 5})
    return frame, meta


def test_every_pipeline_draws_per_sample_by_default() -> None:
    assert inspect.signature(impute_values).parameters["sample_wise"].default is True
    assert (
        inspect.signature(impute_values_with_diagnostics).parameters["sample_wise"].default
        is True
    )
    assert ImputationRunRequest(kind="protein").sampleWise is True


@pytest.mark.requires_r()
def test_the_r_package_also_draws_per_sample_by_default(rscript) -> None:
    """The R default is read from the sourced function and confirmed by a call.

    `formals()` gives the default the R functions actually declare; the call
    without `sample_wise` must then give exactly the per-sample result, and a
    different one from the global draw on a frame whose samples sit at
    different levels.
    """
    import subprocess

    script = """
      suppressMessages(source("proteomicscopylot/notebook_functions.R"))
      set.seed(3)
      d <- as.data.frame(matrix(rnorm(400, 22, 2), ncol = 4,
                                dimnames = list(NULL, c("A1", "A2", "B1", "B2"))))
      d$B1 <- d$B1 + 3; d$B2 <- d$B2 + 3
      d[c(1, 5, 9), "A1"] <- NA; d[c(2, 6), "B1"] <- NA
      m <- data.frame(sample = names(d), condition = c("A", "A", "B", "B"))
      default <- impute_values(d, m)
      cat("FORMAL", isTRUE(formals(impute_values)$sample_wise), "\\n")
      cat("SAME_AS_PER_SAMPLE", identical(default, impute_values(d, m, sample_wise = TRUE)), "\\n")
      cat("SAME_AS_GLOBAL", identical(default, impute_values(d, m, sample_wise = FALSE)), "\\n")
    """
    result = subprocess.run([rscript, "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    answers = dict(line.split()[:2] for line in result.stdout.splitlines() if line.strip())
    message = (
        "the R functions still draw globally by default; the three implementations "
        "must agree on this or the same call gives different numbers per language"
    )
    assert answers["FORMAL"] == "TRUE", message
    assert answers["SAME_AS_PER_SAMPLE"] == "TRUE", message
    assert answers["SAME_AS_GLOBAL"] == "FALSE", message


def test_a_per_sample_draw_lands_near_that_sample_own_floor() -> None:
    frame, meta = _offset_frame()
    own_floor = np.nanquantile(frame[KO].to_numpy(), 0.01)
    combined_floor = np.nanquantile(frame[WT + KO].to_numpy(), 0.01)
    assert own_floor - combined_floor > 0.3, "fixture lost its loading offset"

    per_sample = impute_values(frame.copy(), meta).loc[0, "KO_1"]
    global_draw = impute_values(frame.copy(), meta, sample_wise=False).loc[0, "KO_1"]

    assert abs(per_sample - own_floor) < abs(global_draw - own_floor), (
        f"the default draw ({per_sample:.2f}) should sit nearer the sample's own "
        f"detection floor ({own_floor:.2f}) than the global draw ({global_draw:.2f})"
    )


def test_a_global_draw_is_still_available() -> None:
    frame, meta = _offset_frame()
    a = impute_values(frame.copy(), meta, sample_wise=False).loc[0, "KO_1"]
    b = impute_values(frame.copy(), meta, sample_wise=False).loc[0, "KO_1"]
    assert a == b
    assert a != impute_values(frame.copy(), meta).loc[0, "KO_1"]


def test_the_draw_is_still_reproducible_for_a_given_seed() -> None:
    frame, meta = _offset_frame()
    first = impute_values(frame.copy(), meta, seed=99)[WT + KO].to_numpy()
    second = impute_values(frame.copy(), meta, seed=99)[WT + KO].to_numpy()
    assert np.array_equal(first, second, equal_nan=True)


def _edge_frame():
    frame = pd.DataFrame({"varying": [10., 12., 14., np.nan],
        "constant": [14.05, 14.05, 14.05, np.nan],
        "singleton": [10., np.nan, np.nan, np.nan], "empty": [np.nan]*4,
        "zero": [0., 1., 2., np.nan]})
    return frame, pd.DataFrame({"sample": frame.columns, "condition": "A"})


@pytest.mark.parametrize("method", ["quantile", "numerical"])
@pytest.mark.parametrize("sample_wise", [True, False])
def test_common_imputation_parameters_and_missingness(method, sample_wise, monkeypatch):
    frame, meta = _edge_frame()
    original = frame.copy(deep=True)
    calls = []
    class Recorder:
        def normal(self, center, spread, size):
            calls.append((float(center), float(spread), int(size)))
            return np.full(size, center)
    monkeypatch.setattr(np.random, "default_rng", lambda seed: Recorder())
    result = impute_values_with_diagnostics(frame, list(frame), method=method, sample_wise=sample_wise)
    backend_calls = calls.copy()
    calls.clear()
    if sample_wise:
        with pytest.warns(RuntimeWarning, match="Missing values left unchanged"):
            notebook = impute_values(frame, meta, method=method, sample_wise=True)
    else:
        notebook = impute_values(frame, meta, method=method, sample_wise=False)
    pd.testing.assert_frame_equal(result.imputed_data, notebook)
    assert backend_calls == calls
    assert result.skipped_samples == (["constant", "singleton", "empty"] if sample_wise else [])
    assert result.missing_after == (8 if sample_wise else 0)
    for (center, spread, size), column in zip(calls, ["varying", "zero"] if sample_wise else frame.columns):
        values = frame[column].dropna().to_numpy() if sample_wise else frame.to_numpy().ravel()
        values = values[~np.isnan(values)]
        sd = np.std(values, ddof=1)
        expected = np.quantile(values, .01) if method == "quantile" else values.mean() - 1.8 * sd
        assert center == pytest.approx(expected)
        assert spread == pytest.approx(.3 * sd)
    pd.testing.assert_frame_equal(frame, original)
    np.testing.assert_array_equal(result.imputed_data.to_numpy()[frame.notna()], frame.to_numpy()[frame.notna()])


@pytest.mark.parametrize("values", [[np.nan, np.nan], [10., np.nan], [14.05,14.05,np.nan]])
def test_unusable_global_distribution_is_rejected(values):
    frame = pd.DataFrame({"A": values})
    meta = pd.DataFrame({"sample": ["A"], "condition": "A"})
    with pytest.raises(ValueError, match="Global imputation requires"):
        impute_values_with_diagnostics(frame, ["A"], sample_wise=False)
    with pytest.raises(ValueError, match="Global imputation requires"):
        impute_values(frame, meta, sample_wise=False)


def test_unresolved_values_are_reported_and_json_safe(monkeypatch):
    from app.services import data_tools
    from app.services.runtime_cache import invalidate_runtime_cache
    invalidate_runtime_cache("imputation test")
    frame, meta = _edge_frame()
    monkeypatch.setattr(data_tools, "_best_imputation_source", lambda kind: ("filtered", frame, []))
    monkeypatch.setattr(data_tools, "_get_sample_columns", lambda kind, data: list(frame))
    monkeypatch.setattr(data_tools, "_persist_imputation_result", lambda *args, **kwargs: None)
    result = data_tools.run_imputation(ImputationRunRequest(kind="protein"))
    assert result.missingAfter == 8
    assert result.warnings and "constant" in result.warnings[0]
    assert result.preview[0]["empty"] is None
    assert "NaN" not in result.model_dump_json()


def test_all_missing_samplewise_data_stays_missing(monkeypatch):
    from app.services import data_tools
    from app.services.runtime_cache import invalidate_runtime_cache
    invalidate_runtime_cache("imputation test")
    frame = pd.DataFrame({"A": [np.nan, np.nan]})
    monkeypatch.setattr(data_tools, "_best_imputation_source", lambda kind: ("filtered", frame, []))
    monkeypatch.setattr(data_tools, "_get_sample_columns", lambda kind, data: ["A"])
    monkeypatch.setattr(data_tools, "_persist_imputation_result", lambda *args, **kwargs: None)
    result = data_tools.run_imputation(ImputationRunRequest(kind="protein"))
    assert result.missingAfter == 2
    assert result.std is None and result.mean is None
    assert result.warnings
    assert "NaN" not in result.model_dump_json()


@pytest.mark.parametrize("method", ["quantile", "numerical"])
@pytest.mark.parametrize("sample_wise", [True, False])
@pytest.mark.requires_r()
def test_r_draw_parameters_and_fallbacks_match_backend(method, sample_wise):
    import subprocess
    from app.services.r_runtime import detect_r_runtime
    runtime = detect_r_runtime()
    frame, meta = _edge_frame()
    expected = impute_values_with_diagnostics(frame, list(frame), method=method, sample_wise=sample_wise)
    script = f'''
      source("proteomicscopylot/notebook_functions.R")
      d <- data.frame(varying=c(10,12,14,NA),constant=c(14.05,14.05,14.05,NA),
        singleton=c(10,NA,NA,NA),empty=rep(NA_real_,4),zero=c(0,1,2,NA))
      m <- data.frame(sample=names(d),condition="A")
      rnorm <- function(n,mean,sd) {{cat(sprintf("DRAW %.17g %.17g %d\\n",mean,sd,n)); rep(mean,n)}}
      out <- impute_values(d,m,method="{method}",sample_wise={str(sample_wise).upper()})
      stopifnot(sum(is.na(out)) == {expected.missing_after},all(as.matrix(out)[!is.na(d)] == as.matrix(d)[!is.na(d)]))
      for (v in list(c(NA_real_,NA_real_),c(10,NA),c(14.05,14.05,NA))) {{
        empty <- data.frame(A=v)
        em <- data.frame(sample="A",condition="A")
        stopifnot(inherits(try(impute_values(empty,em,sample_wise=FALSE),silent=TRUE),"try-error"))
        unchanged <- suppressWarnings(impute_values(empty,em,sample_wise=TRUE))
        stopifnot(identical(unchanged,empty))
      }}
    '''
    result = subprocess.run([runtime["executable"], "-e", script],cwd=ROOT,
                            capture_output=True,text=True,timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    draws = [list(map(float,line.split()[1:])) for line in result.stdout.splitlines() if line.startswith("DRAW ")]
    expected_draws = expected.draw_components
    if not sample_wise:
        center, sd, _ = expected_draws[0]
        expected_draws = [(center,sd,int(frame[c].isna().sum())) for c in frame]
    np.testing.assert_allclose(draws,expected_draws,rtol=1e-12)
