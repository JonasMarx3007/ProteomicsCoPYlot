"""Each projection method's default scaling: the backend half of one convention.

PCA is conventionally run centred and UMAP/t-SNE on unit variance. The frontend
moves the scaling selector to that default when the method changes, and the
backend resolves a saved `auto` to it. The table both are held to is
tests/fixtures/pca_default_scaling.json; the frontend half, and what the
selector offers, is frontend/tests/component/pca-scaling.test.tsx.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.functions import resolve_feature_scaling

DEFAULTS = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "pca_default_scaling.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("method,scaling", sorted(DEFAULTS.items()))
def test_auto_resolves_to_the_method_s_default(method: str, scaling: str) -> None:
    assert resolve_feature_scaling("auto", method=method) == scaling


def test_auto_without_a_method_is_pca_s_default() -> None:
    """Nothing writes `auto` any more; states saved before the change still hold it."""
    assert resolve_feature_scaling("auto") == DEFAULTS["PCA"]


@pytest.mark.parametrize("method", sorted(DEFAULTS))
@pytest.mark.parametrize("scaling", ["centered", "unit_variance"])
def test_a_named_scaling_is_used_whatever_the_method(method: str, scaling: str) -> None:
    assert resolve_feature_scaling(scaling, method=method) == scaling
