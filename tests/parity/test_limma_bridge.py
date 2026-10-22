"""The moderated t-tests: the app's R bridge, the R functions and limma itself agree.

The four `moderated*` test types delegate to Bioconductor limma (r_limma.py),
and the R notebook functions call limma directly. Both must give the p-values a
plain `lmFit` + `eBayes` gives, on the same rows, with the same missing-value
handling; and the pip package, which cannot call R, must refuse them by name.
Skipped where Rscript or limma is absent; required in CI (COPYLOT_REQUIRE_LIMMA=1).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from app.schemas.stats import VolcanoRequest  # noqa: E402
from app.services import r_limma  # noqa: E402
from app.services.r_runtime import detect_r_runtime  # noqa: E402
from app.services.stats_tools import _volcano_dataframe  # noqa: E402


def _limma_ready() -> bool:
    r_limma.clear_limma_availability_cache()
    return bool(r_limma.limma_availability().get("available"))


requires_limma = pytest.mark.skipif(
    not _limma_ready() and os.environ.get("COPYLOT_REQUIRE_LIMMA") != "1",
    reason="Rscript with Bioconductor limma is not available",
)
MODERATED = ["moderated", "moderated_robust", "moderated_paired", "moderated_robust_paired"]


def _fixture(rows: int = 300):
    rng = np.random.default_rng(11)
    values = rng.normal(20, 1, (rows, 6))
    values[:30, :3] += 1.2
    values[rng.random((rows, 6)) < 0.04] = np.nan
    frame = pd.DataFrame(values, columns=[f"Ctrl_{i}" for i in (1, 2, 3)] + [f"Treat_{i}" for i in (1, 2, 3)])
    frame.insert(0, "ProteinNames", [f"G{k}" for k in range(rows)])
    meta = pd.DataFrame({"sample": frame.columns[1:], "condition": ["Ctrl"] * 3 + ["Treat"] * 3,
                         "pair_id": ["p1", "p2", "p3"] * 2})
    return frame, meta


def test_limma_is_available_where_it_is_required() -> None:
    if os.environ.get("COPYLOT_REQUIRE_LIMMA") == "1":
        assert _limma_ready(), r_limma.limma_availability()


@requires_limma
@pytest.mark.parametrize("test_type", MODERATED)
def test_app_r_functions_and_limma_agree(tmp_path, test_type: str) -> None:
    frame, meta = _fixture()
    _, _, app_table, _ = _volcano_dataframe(
        kind="protein", condition1="Ctrl", condition2="Treat", identifier="workflow",
        p_value_threshold=0.05, log2fc_threshold=1, test_type=test_type, use_uncorrected=False,
        data_source="data", frame_override=frame, metadata_override=meta,
    )
    frame.to_csv(tmp_path / "data.csv", index=False)
    meta.to_csv(tmp_path / "meta.csv", index=False)
    paired = test_type.endswith("_paired")
    robust = "robust" in test_type
    script = f'''
      source("proteomicscopylot/notebook_functions.R")
      suppressMessages(library(limma))
      data <- read.csv("{tmp_path.as_posix()}/data.csv", check.names = FALSE)
      meta <- read.csv("{tmp_path.as_posix()}/meta.csv", check.names = FALSE)
      pkg <- volcano_data_f(data, meta, "Ctrl", "Treat", workflow = "Protein", test_type = "{test_type}")
      write.csv(pkg[, c("ProteinNames", "log2FC", "pval", "adj_pval")], "{tmp_path.as_posix()}/r_pkg.csv", row.names = FALSE)
      # limma directly, on exactly the rows the app tested
      x <- as.matrix(data[, c("Ctrl_1","Ctrl_2","Ctrl_3")]); y <- as.matrix(data[, c("Treat_1","Treat_2","Treat_3")])
      if ({"TRUE" if paired else "FALSE"}) {{
        d <- x - y
        keep <- rowSums(is.finite(d)) >= 2
        fit <- eBayes(lmFit(d[keep, ], matrix(1, 3, 1, dimnames = list(NULL, "d"))), robust = {"TRUE" if robust else "FALSE"})
        p <- fit$p.value[, "d"]
      }} else {{
        keep <- rowSums(is.finite(x)) >= 2 & rowSums(is.finite(y)) >= 2
        g <- factor(c("a","a","a","b","b","b"), levels = c("b","a"))
        fit <- eBayes(lmFit(cbind(x, y)[keep, ], model.matrix(~ g)), robust = {"TRUE" if robust else "FALSE"})
        p <- fit$p.value[, "ga"]
      }}
      write.csv(data.frame(ProteinNames = data$ProteinNames[keep], pval = p), "{tmp_path.as_posix()}/r_direct.csv", row.names = FALSE)
    '''
    result = subprocess.run([detect_r_runtime()["executable"], "-e", script],
                            cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stderr
    r_pkg = pd.read_csv(tmp_path / "r_pkg.csv").set_index("ProteinNames")
    r_direct = pd.read_csv(tmp_path / "r_direct.csv").set_index("ProteinNames")
    app = app_table.set_index("ProteinNames")

    assert set(app.index) == set(r_direct.index), "the app tested exactly the rows limma can fit"
    assert set(app.index) == set(r_pkg.index), "the R functions tested the same rows"
    for name, other in (("limma", r_direct), ("R functions", r_pkg)):
        joined = app[["pval"]].join(other[["pval"]], rsuffix="_other")
        finite = joined.notna().all(axis=1)
        assert np.allclose(joined.loc[finite, "pval"], joined.loc[finite, "pval_other"], rtol=0, atol=1e-12), name
        assert (joined.isna().all(axis=1) | finite).all(), f"{name}: an unavailable p-value on one side only"
    assert np.allclose(app["log2FC"], r_pkg["log2FC"], atol=1e-12)
    assert np.allclose(app["adj_pval"].dropna(), r_pkg["adj_pval"].dropna(), atol=1e-12)
    # Moderation changes the p-value only; the plain test of the same design shares every other column.
    plain = "paired" if paired else "unpaired"
    _, _, plain_table, _ = _volcano_dataframe(
        kind="protein", condition1="Ctrl", condition2="Treat", identifier="workflow",
        p_value_threshold=0.05, log2fc_threshold=1, test_type=plain, use_uncorrected=False,
        data_source="data", frame_override=frame, metadata_override=meta,
    )
    pd.testing.assert_series_equal(app_table["log2FC"], plain_table["log2FC"])
    assert not np.allclose(app_table["pval"].fillna(-1), plain_table["pval"].fillna(-1))


def test_the_pip_package_refuses_moderated_tests_by_name() -> None:
    from proteomicscopylot import notebook_functions as pkg
    frame, meta = _fixture(40)
    for test_type in MODERATED:
        with pytest.raises(ValueError, match="Bioconductor limma"):
            pkg.volcano_data_f(frame, meta, "Ctrl", "Treat", workflow="Protein", test_type=test_type)
    with pytest.raises(ValueError, match="test_type must be one of"):
        pkg.resolve_test_type("anova")


def test_the_request_schema_and_the_runtime_report_name_the_same_tests() -> None:
    from typing import get_args
    from app.schemas.stats import StatsTestType
    from app.services.functions import _TEST_TYPES, is_moderated_test_type
    assert set(get_args(StatsTestType)) == set(_TEST_TYPES)
    assert {name for name in _TEST_TYPES if is_moderated_test_type(name)} == set(MODERATED)
    VolcanoRequest(kind="protein", condition1="A", condition2="B", testType="moderated_robust_paired")


def test_the_version_comes_from_the_cached_probe_without_a_second_rscript(monkeypatch) -> None:
    """One probe answers installed + versions (2026-10-22); the Methods text reads the cache."""
    import subprocess
    r_limma.clear_limma_availability_cache()
    try:
        availability = r_limma.limma_availability()
        if not availability.get("available"):
            pytest.skip("limma is not installed here")
        assert availability["packageVersion"] and availability["rVersion"]

        def no_spawn(*args, **kwargs):
            raise AssertionError("limma_reference_version must not start R")

        monkeypatch.setattr(subprocess, "run", no_spawn)
        assert r_limma.limma_reference_version() == availability["packageVersion"]
    finally:
        r_limma.clear_limma_availability_cache()
