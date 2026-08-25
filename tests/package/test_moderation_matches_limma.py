from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))


def _rscript() -> str | None:
    try:
        from app.services.r_runtime import detect_r_runtime
    except Exception:
        return None
    runtime = detect_r_runtime()
    return str(runtime["executable"]) if runtime.get("available") else None


RSCRIPT = _rscript()


def _limma_available() -> bool:
    if RSCRIPT is None:
        return False
    probe = subprocess.run(
        [RSCRIPT, "-e", 'cat(requireNamespace("limma", quietly=TRUE))'],
        capture_output=True, text=True, timeout=180,
    )
    return "TRUE" in probe.stdout


requires_limma = pytest.mark.skipif(
    not _limma_available(), reason="R with the limma package is not available"
)

RESIDUAL_DOF = 4.0
FEATURES = 800


def _variances() -> np.ndarray:
    rng = np.random.default_rng(5)
    true_variance = 0.4 * (6.0 / rng.chisquare(6.0, FEATURES))
    return true_variance * rng.chisquare(RESIDUAL_DOF, FEATURES) / RESIDUAL_DOF


def _limma_reference(variances: np.ndarray) -> dict:
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        fixture = Path(directory) / "variances.csv"
        out = Path(directory) / "limma.csv"
        np.savetxt(fixture, variances, delimiter=",", header="variance", comments="")
        script = "; ".join([
            "suppressWarnings(suppressMessages(library(limma)))",
            f"v <- read.csv('{fixture.as_posix()}')$variance",
            f"s <- limma::squeezeVar(v, {RESIDUAL_DOF})",
            "res <- data.frame(post = s$var.post, var_prior = s$var.prior, df_prior = s$df.prior)",
            f"write.csv(res, '{out.as_posix()}', row.names = FALSE)",
        ])
        completed = subprocess.run(
            [RSCRIPT, "-e", script], capture_output=True, text=True, timeout=600, cwd=str(ROOT)
        )
        assert completed.returncode == 0, completed.stderr[-400:]
        assert out.exists(), f"limma produced no output: {completed.stdout[-300:]}"

        import csv

        with out.open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        return {
            "post": [float(row["post"]) for row in rows],
            "var_prior": float(rows[0]["var_prior"]),
            "df_prior": float(rows[0]["df_prior"]),
        }


@pytest.fixture(scope="module")
def reference() -> dict:
    if not _limma_available():
        pytest.skip("limma is not available")
    return _limma_reference(_variances())


def test_the_fixture_is_not_degenerate(reference) -> None:
    assert np.isfinite(reference["df_prior"])
    assert 1.0 < reference["df_prior"] < 100.0, reference["df_prior"]


@requires_limma
def test_the_web_app_matches_limma(reference) -> None:
    from app.services.functions import _fit_variance_prior, squeeze_variance

    variances = _variances()
    dof = np.full(FEATURES, RESIDUAL_DOF)

    var_prior, df_prior = _fit_variance_prior(variances, dof)
    assert var_prior == pytest.approx(reference["var_prior"], rel=1e-10)
    assert df_prior == pytest.approx(reference["df_prior"], rel=1e-10)

    posterior = squeeze_variance(variances, dof)
    posterior = posterior[0] if isinstance(posterior, tuple) else posterior
    assert np.allclose(np.asarray(posterior, dtype=float), reference["post"], rtol=1e-10, atol=1e-12)


@requires_limma
def test_the_pip_package_matches_limma(reference) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_nb_limma", ROOT / "proteomicscopylot" / "notebook_functions.py"
    )
    notebook = importlib.util.module_from_spec(spec)
    sys.modules["_nb_limma"] = notebook
    spec.loader.exec_module(notebook)

    variances = _variances()
    dof = np.full(FEATURES, RESIDUAL_DOF)
    posterior = notebook.squeeze_variance(variances, dof)
    posterior = posterior[0] if isinstance(posterior, tuple) else posterior
    assert np.allclose(np.asarray(posterior, dtype=float), reference["post"], rtol=1e-10, atol=1e-12)


@requires_limma
def test_the_r_package_matches_limma() -> None:
    script = (
        'suppressWarnings(suppressMessages({library(limma); '
        'source("proteomicscopylot/notebook_functions.R")}));'
        'set.seed(1); v <- 0.4*(6/rchisq(800,6)) * rchisq(800,4)/4;'
        f'ref <- limma::squeezeVar(v, {RESIDUAL_DOF});'
        'ours <- squeeze_variance(v, rep(4, 800));'
        'post <- if (is.list(ours)) ours[[1]] else ours;'
        'cat(max(abs(post - ref$var.post)), is.finite(ref$df.prior))'
    )
    completed = subprocess.run(
        [RSCRIPT, "-e", script], capture_output=True, text=True, timeout=600, cwd=str(ROOT)
    )
    assert completed.returncode == 0, completed.stderr[-400:]
    parts = completed.stdout.split()
    largest_difference = float(parts[0])
    assert parts[-1] == "TRUE", "the R fixture degenerated to an infinite prior"
    assert largest_difference < 1e-10, f"R differs from limma by {largest_difference:.3e}"
