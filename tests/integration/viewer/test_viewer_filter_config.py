from __future__ import annotations

import typing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

from app.schemas.annotation import (
    AnnotationFilterConfig,
    NormalizationMethod,
)
from app.services.viewer_bootstrap import (
    _filter_config,
    _normalize_normalization,
)

METHODS = sorted(typing.get_args(NormalizationMethod))


def test_every_filter_field_can_be_set_from_viewer_config() -> None:
    config = {
        "filter_method_protein": "percentage",
        "filter_percentage_protein": 80,
        "filter_min_protein": 2,
        "filter_mode_protein": "overall",
        "normalization_protein": "vsn",
        "normalization_fit_protein": "complete_features",
    }
    resolved = _filter_config(config, "protein")
    defaults = AnnotationFilterConfig().model_dump()
    unchanged = [
        field
        for field, value in resolved.model_dump().items()
        if value == defaults[field]
    ]
    assert not unchanged, (
        f"viewer_config could not influence {unchanged}; "
        "add the key to _filter_config or the field is unreachable for viewer projects"
    )


@pytest.mark.parametrize("method", METHODS)
def test_per_kind_normalization_key(method: str) -> None:
    assert _filter_config({"normalization_protein": method}, "protein").normalization == method


@pytest.mark.parametrize("method", METHODS)
def test_shared_normalization_key_applies_to_every_kind(method: str) -> None:
    for suffix in ("protein", "phospho"):
        assert _filter_config({"normalization": method}, suffix).normalization == method


@pytest.mark.parametrize("suffix", ["phosprot", "phosphoprotein"])
@pytest.mark.parametrize("method", METHODS)
def test_phosprot_never_applies_a_second_normalization(
    suffix: str,
    method: str,
) -> None:
    assert _filter_config({"normalization": method}, suffix).normalization == "none"
    assert _filter_config({f"normalization_{suffix}": method}, suffix).normalization == "none"


def test_per_kind_key_overrides_the_shared_key() -> None:
    config = {"normalization": "median", "normalization_protein": "quantile"}
    assert _filter_config(config, "protein").normalization == "quantile"
    assert _filter_config(config, "phospho").normalization == "median"


def test_absent_normalization_defaults_to_none() -> None:
    assert _filter_config({}, "protein").normalization == "none"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("median-centering", "median"),
        ("median_center", "median"),
        ("Quantile Normalization", "quantile"),
        ("VSN", "vsn"),
        ("off", "none"),
        ("disabled", "none"),
        ("", "none"),
    ],
)
def test_aliases_are_accepted(raw: str, expected: str) -> None:
    assert _normalize_normalization(raw) == expected


def test_unknown_value_falls_back_rather_than_raising() -> None:
    assert _normalize_normalization("loess") == "none"
    assert _filter_config({"normalization": "nonsense"}, "protein").normalization == "none"


def test_other_filter_keys_still_work() -> None:
    config = {
        "filter_method_phospho": "percentage",
        "filter_percentage_phospho": 55,
        "filter_mode_phospho": "in_at_least_one_group",
    }
    resolved = _filter_config(config, "phospho")
    assert resolved.method == "percentage"
    assert resolved.minPercentage == 55.0
    assert resolved.mode == "in_at_least_one_group"


def test_a_valid_normalization_produces_no_warning() -> None:
    from app.services.viewer_bootstrap import _filter_config

    warnings: list[str] = []
    config = _filter_config({"normalization": "quantile"}, "protein", warnings)
    assert config.normalization == "quantile"
    assert warnings == []


def test_explicitly_disabling_normalization_produces_no_warning() -> None:
    from app.services.viewer_bootstrap import _filter_config

    for value in ("none", "off", "disabled", ""):
        warnings: list[str] = []
        config = _filter_config({"normalization": value}, "protein", warnings)
        assert config.normalization == "none"
        assert warnings == [], value


def test_a_mistyped_normalization_is_reported_and_still_falls_back() -> None:
    from app.services.viewer_bootstrap import _filter_config

    warnings: list[str] = []
    config = _filter_config({"normalization": "quantle"}, "protein", warnings)

    assert config.normalization == "none", "the fallback itself must not change"
    assert len(warnings) == 1
    assert "quantle" in warnings[0]
    assert "no normalization was applied" in warnings[0]


def test_a_mistyped_filter_mode_is_reported_and_still_falls_back() -> None:
    from app.services.viewer_bootstrap import _filter_config

    warnings: list[str] = []
    config = _filter_config({"filter_mode_protein": "pergroup"}, "protein", warnings)

    assert config.mode == "per_group"
    assert len(warnings) == 1
    assert "pergroup" in warnings[0]


def test_recognised_filter_mode_spellings_stay_quiet() -> None:
    from app.services.viewer_bootstrap import _filter_config

    for value, expected in (
        ("per-group", "per_group"),
        ("per group", "per_group"),
        ("overall", "overall"),
        ("in_at_least_one_group", "in_at_least_one_group"),
    ):
        warnings: list[str] = []
        config = _filter_config({"filter_mode_protein": value}, "protein", warnings)
        assert config.mode == expected, value
        assert warnings == [], value
