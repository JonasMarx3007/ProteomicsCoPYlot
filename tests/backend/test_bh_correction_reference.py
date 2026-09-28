from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from scipy.stats import false_discovery_control

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.stats_tools import _bh_adjust


def _reference(pvalues: np.ndarray) -> np.ndarray:
    return false_discovery_control(pvalues, method="bh")


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
def test_matches_scipy_on_random_p_value_sets(seed: int) -> None:
    rng = np.random.default_rng(seed)
    pvalues = np.concatenate([rng.uniform(0, 0.01, 5), rng.uniform(0, 1, 45)])
    assert np.allclose(_bh_adjust(pvalues), _reference(pvalues), rtol=1e-12, atol=1e-15)


@pytest.mark.parametrize(
    "pvalues",
    [
        [0.01],
        [0.5, 0.5, 0.5],
        [0.001, 0.002, 0.003, 0.9],
        [0.9, 0.8, 0.7, 0.001],
        [0.0, 1.0],
        list(np.linspace(0.001, 0.999, 200)),
    ],
    ids=["single", "identical", "step-up-binds", "unsorted", "bounds", "uniform-200"],
)
def test_matches_scipy_on_shapes_that_stress_the_step_up(pvalues) -> None:
    values = np.asarray(pvalues, dtype=float)
    assert np.allclose(_bh_adjust(values), _reference(values), rtol=1e-12, atol=1e-15)


def test_the_result_is_monotone_in_the_raw_p_value() -> None:
    rng = np.random.default_rng(7)
    pvalues = rng.uniform(0, 1, 100)
    adjusted = _bh_adjust(pvalues)
    order = np.argsort(pvalues)
    assert np.all(np.diff(adjusted[order]) >= -1e-12)


def test_adjusted_p_is_never_below_the_raw_p_or_above_one() -> None:
    rng = np.random.default_rng(9)
    pvalues = rng.uniform(0, 1, 100)
    adjusted = _bh_adjust(pvalues)
    assert np.all(adjusted >= pvalues - 1e-12)
    assert np.all(adjusted <= 1.0 + 1e-12)


def test_the_reference_itself_disagrees_with_the_wrong_step_up() -> None:
    rng = np.random.default_rng(0)
    pvalues = np.concatenate([rng.uniform(0, 0.01, 5), rng.uniform(0, 1, 15)])
    order = np.argsort(pvalues)
    ranked = pvalues[order]
    raw = ranked * len(ranked) / np.arange(1, len(ranked) + 1)

    wrong = np.empty_like(raw)
    wrong[order] = np.clip(np.maximum.accumulate(raw), 0, 1)

    assert not np.allclose(wrong, _reference(pvalues)), (
        "the wrong step-up should not match the reference; if it does, this "
        "file cannot detect the bug it exists for"
    )


def _fallback_module(monkeypatch, path: Path, module_name: str):
    import builtins
    import importlib.util

    real_import = builtins.__import__

    def _no_statsmodels(name, *args, **kwargs):
        if name.startswith("statsmodels"):
            raise ModuleNotFoundError("statsmodels is hidden for this test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_statsmodels)
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("module_name", "relative"),
    [
        ("_fallback_backend", "backend/app/services/functions.py"),
        ("_fallback_pip", "proteomicscopylot/notebook_functions.py"),
    ],
)
def test_the_statsmodels_free_fallback_matches_the_reference(
    monkeypatch, module_name: str, relative: str
) -> None:
    module = _fallback_module(monkeypatch, ROOT / relative, module_name)
    assert module.multipletests.__module__ == module_name, (
        "statsmodels was still importable, so the fallback was not exercised"
    )

    rng = np.random.default_rng(3)
    for _ in range(5):
        pvalues = np.concatenate([rng.uniform(0, 0.01, 4), rng.uniform(0, 1, 26)])
        adjusted = module.multipletests(pvalues, method="fdr_bh")[1]
        assert np.allclose(adjusted, _reference(pvalues), rtol=1e-12, atol=1e-15)


def test_the_fallback_refuses_methods_it_does_not_implement(monkeypatch) -> None:
    module = _fallback_module(
        monkeypatch, ROOT / "backend/app/services/functions.py", "_fallback_methods"
    )
    # 2026-09-25: the backend's BH no longer goes through statsmodels at all
    # (stats_core.bh_adjust), so the refusal names the real limit.
    with pytest.raises(ValueError, match="Only method='fdr_bh'"):
        module.multipletests(np.array([0.01, 0.5]), method="bonferroni")
