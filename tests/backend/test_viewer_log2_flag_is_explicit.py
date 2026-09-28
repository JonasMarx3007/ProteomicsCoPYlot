"""The viewer config must state whether each file is already log2 transformed.

The viewer never auto-detects the scale and never falls back to a default:
a linear matrix loaded as log2 gives fold changes, CVs and tests that are
numerically valid and wrong everywhere. A config that leaves the question
open for any file it names is refused as a whole, before a file is read.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import viewer_bootstrap
from app.services.viewer_bootstrap import _log2_flag, _parse_log2_flag, _validate_log2_flags

ROOT = Path(__file__).resolve().parents[2]


def _package(**overrides):
    package = {
        "protein_file": "protein.tsv",
        "phospho_file": "none",
        "phosprot_file": "none",
        "log2_transform_protein": True,
    }
    package.update(overrides)
    return package


def test_a_complete_config_passes():
    _validate_log2_flags({"A": _package()})


def test_a_missing_flag_for_a_named_file_is_refused():
    with pytest.raises(ValueError) as excinfo:
        _validate_log2_flags({"A": _package(phospho_file="phospho.tsv")})
    message = str(excinfo.value)
    assert "'A' has 'phospho_file' but no 'log2_transform_phospho'" in message
    assert "must state for every dataset file" in message


@pytest.mark.parametrize("value", ["maybe", 2, None, [True], "log2"])
def test_an_unreadable_flag_is_refused(value):
    with pytest.raises(ValueError, match="unreadable 'log2_transform_protein'"):
        _validate_log2_flags({"A": _package(log2_transform_protein=value)})


def test_a_level_without_a_file_needs_no_flag():
    _validate_log2_flags({"A": _package(phospho_file="none", phosprot_file="")})


def test_every_problem_is_listed_at_once():
    with pytest.raises(ValueError) as excinfo:
        _validate_log2_flags(
            {
                "A": _package(log2_transform_protein="?"),
                "B": _package(phosprot_file="pp.csv"),
            }
        )
    message = str(excinfo.value)
    assert "'A' has an unreadable" in message and "'B' has 'phosprot_file' but no" in message


@pytest.mark.parametrize(
    "value,expected",
    [(True, True), (False, False), ("true", True), ("FALSE", False), ("yes", True), ("off", False), (1, True), (0, False)],
)
def test_explicit_spellings_are_read(value, expected):
    assert _parse_log2_flag(value) is expected
    assert _log2_flag({"log2_transform_phospho": value}, "phospho") is expected


def test_load_viewer_state_refuses_before_reading_any_file(tmp_path, monkeypatch):
    config = {"datasets": {"A": {"protein_file": "missing.tsv"}}}
    path = tmp_path / "viewer_config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        viewer_bootstrap, "_resolve_config_file_path", lambda **kw: calls.append(kw) or None
    )
    with pytest.raises(ValueError, match="log2_transform_protein"):
        viewer_bootstrap.load_viewer_state(path)
    assert calls == []


def test_the_repo_viewer_config_states_every_flag():
    config = json.loads((ROOT / "viewer_config.json").read_text(encoding="utf-8"))
    _validate_log2_flags(config["datasets"])
    for name, package in config["datasets"].items():
        for suffix in ("protein", "phospho", "phosphoprotein"):
            assert isinstance(package.get(f"log2_transform_{suffix}"), bool), (name, suffix)


# --- metadata is required for every dataset file ----------------------------

from app.services.viewer_bootstrap import _validate_metadata_requirements  # noqa: E402


def _meta_package(tmp_path: Path, **overrides):
    (tmp_path / "meta.csv").write_text("sample,condition\nS1,A\n", encoding="utf-8")
    (tmp_path / "meta_phospho.csv").write_text("sample,condition\nS1,A\n", encoding="utf-8")
    package = {
        "protein_file": "protein.tsv",
        "phospho_file": "none",
        "phosprot_file": "none",
        "metadata_profiles": {"P": {"meta_file": "meta.csv", "meta_phospho_file": "none"}},
    }
    package.update(overrides)
    return package


def test_metadata_present_for_every_level_passes(tmp_path):
    package = _meta_package(
        tmp_path,
        phospho_file="phospho.tsv",
        metadata_profiles={"P": {"meta_file": "meta.csv", "meta_phospho_file": "meta_phospho.csv"}},
    )
    _validate_metadata_requirements({"A": package}, tmp_path)


def test_a_dataset_without_any_metadata_is_refused(tmp_path):
    package = _meta_package(tmp_path)
    del package["metadata_profiles"]
    with pytest.raises(ValueError, match="'A' has dataset files but no metadata"):
        _validate_metadata_requirements({"A": package}, tmp_path)


def test_a_phospho_file_without_phospho_metadata_is_refused(tmp_path):
    package = _meta_package(tmp_path, phospho_file="phospho.tsv")
    with pytest.raises(ValueError, match="profile 'P' has 'phospho_file' but no 'meta_phospho_file'"):
        _validate_metadata_requirements({"A": package}, tmp_path)


def test_a_phosprot_file_needs_the_phospho_metadata_too(tmp_path):
    package = _meta_package(tmp_path, phosprot_file="pp.csv")
    with pytest.raises(ValueError, match="has 'phosprot_file' but no 'meta_phospho_file'"):
        _validate_metadata_requirements({"A": package}, tmp_path)


def test_a_metadata_file_that_does_not_exist_is_refused(tmp_path):
    package = _meta_package(tmp_path, metadata_profiles={"P": {"meta_file": "gone.csv"}})
    with pytest.raises(ValueError, match="'meta_file' does not exist \\(gone.csv\\)"):
        _validate_metadata_requirements({"A": package}, tmp_path)


def test_the_legacy_single_profile_keys_count(tmp_path):
    package = _meta_package(tmp_path)
    del package["metadata_profiles"]
    package["meta_file"] = "meta.csv"
    _validate_metadata_requirements({"A": package}, tmp_path)


def test_a_package_without_dataset_files_needs_no_metadata(tmp_path):
    _validate_metadata_requirements({"A": {"protein_file": "none"}}, tmp_path)


def test_load_viewer_state_refuses_a_missing_metadata_before_reading_any_file(tmp_path, monkeypatch):
    config = {"datasets": {"A": {"protein_file": "protein.tsv", "log2_transform_protein": True}}}
    path = tmp_path / "viewer_config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        viewer_bootstrap, "_resolve_config_file_path", lambda **kw: calls.append(kw) or None
    )
    with pytest.raises(ValueError, match="no metadata"):
        viewer_bootstrap.load_viewer_state(path)
    assert calls == []


def test_both_shipped_configs_satisfy_the_metadata_rule():
    for config_path in (ROOT / "viewer_config.json", ROOT / "viewer_data" / "HEK293" / "viewer_config.json"):
        config = json.loads(config_path.read_text(encoding="utf-8"))
        _validate_metadata_requirements(config["datasets"], config_path.parent)


# --- filtering and imputation: off unless configured, complete once on -------

from app.services.viewer_bootstrap import (  # noqa: E402
    _validate_filter_settings,
    _validate_imputation_settings,
    _validate_processing_settings,
)


def _proc(**keys):
    package = {"protein_file": "protein.tsv"}
    package.update(keys)
    return {"A": package}


def test_no_filter_keys_means_no_filter_and_passes():
    assert _validate_filter_settings(_proc()) == []


def test_a_filter_threshold_alone_is_refused():
    problems = _validate_filter_settings(_proc(filter_min_protein=3))
    assert any("'filter_method_protein' is missing" in p for p in problems)
    assert any("'filter_mode_protein' is missing" in p for p in problems)


def test_a_complete_at_least_n_filter_passes():
    assert _validate_filter_settings(_proc(filter_method_protein="at_least_n", filter_mode_protein="in at least one group", filter_min_protein=3)) == []


def test_a_percentage_filter_needs_its_percentage():
    problems = _validate_filter_settings(_proc(filter_method_protein="percentage", filter_mode_protein="overall"))
    assert problems == ["'A' level 'protein': method percentage needs 'filter_percentage_protein'"]
    assert _validate_filter_settings(_proc(filter_method_protein="percentage", filter_mode_protein="overall", filter_percentage_protein=70)) == []


@pytest.mark.parametrize("bad", [{"filter_method_protein": "atleast"}, {"filter_mode_protein": "pergroup"}, {"filter_percentage_protein": 150, "filter_method_protein": "percentage"}, {"filter_min_protein": -1}])
def test_unknown_or_out_of_range_filter_values_are_refused(bad):
    package = {"filter_method_protein": "at_least_n", "filter_mode_protein": "per_group", "filter_min_protein": 2}
    package.update(bad)
    assert _validate_filter_settings(_proc(**package)), bad


def test_an_unknown_normalization_is_refused_but_absent_means_none():
    assert _validate_filter_settings(_proc(normalization_protein="vsn")) == []
    assert _validate_filter_settings(_proc(normalization="median")) == []
    assert _validate_filter_settings(_proc(normalization_protein="none")) == []
    assert _validate_filter_settings(_proc(normalization_protein="loess")) == ["'A' level 'protein': 'normalization_protein' 'loess' is not a normalization the tool knows"]


def test_no_imputation_block_or_mode_none_passes():
    assert _validate_imputation_settings(_proc()) == []
    assert _validate_imputation_settings(_proc(imputation={"mode": "none", "q_value": "none", "seed": "none"})) == []
    assert _validate_imputation_settings(_proc(imputation="none")) == []


def test_a_mode_that_is_on_needs_every_parameter():
    problems = _validate_imputation_settings(_proc(imputation={"mode": "perseus", "down_shift": 1.8}))
    assert problems == [
        "'A' level 'protein': imputation mode numerical is on but 'width' is not set",
        "'A' level 'protein': imputation mode numerical is on but 'seed' is not set",
        "'A' level 'protein': imputation mode numerical is on but 'sample_wise' is not set",
    ]
    assert _validate_imputation_settings(_proc(imputation={"mode": "numerical", "down_shift": 1.8, "width": 0.3, "seed": 1, "sample_wise": True})) == []
    assert _validate_imputation_settings(_proc(imputation={"mode": "quantile", "q_value": 0.01, "adjust_std": 0.3, "seed": 1, "sample_wise": False})) == []


def test_a_bare_mode_name_that_is_on_is_refused():
    problems = _validate_imputation_settings(_proc(imputation="numerical"))
    assert len(problems) == 4


def test_a_parameter_written_as_none_counts_as_missing():
    problems = _validate_imputation_settings(_proc(imputation={"mode": "quantile", "q_value": "none", "adjust_std": 0.3, "seed": 1, "sample_wise": True}))
    assert problems == ["'A' level 'protein': imputation mode quantile is on but 'q_value' is not set"]


def test_an_unknown_imputation_mode_is_refused():
    assert _validate_imputation_settings(_proc(imputation={"mode": "knn"})) == [
        "'A' level 'protein': imputation mode 'knn' is not one the tool knows (numerical, quantile)"
    ]


def test_per_level_imputation_blocks_are_checked_per_level():
    config = _proc(phospho_file="p.tsv", imputation={"protein": {"mode": "none"}, "phospho": {"mode": "numerical"}})
    problems = _validate_imputation_settings(config)
    assert all("level 'phospho'" in p for p in problems) and len(problems) == 4


def test_processing_problems_are_reported_together():
    with pytest.raises(ValueError, match="turns on filtering or imputation without stating its settings") as excinfo:
        _validate_processing_settings(_proc(filter_min_protein=3, imputation="quantile"))
    assert "filter_method_protein" in str(excinfo.value) and "'q_value' is not set" in str(excinfo.value)


def test_both_shipped_configs_state_their_processing_completely():
    for config_path in (ROOT / "viewer_config.json", ROOT / "viewer_data" / "HEK293" / "viewer_config.json"):
        _validate_processing_settings(json.loads(config_path.read_text(encoding="utf-8"))["datasets"])


@pytest.mark.parametrize("value", [3.7, "3.7", float("inf"), float("nan"), True])
def test_filter_counts_cannot_be_truncated_or_nonfinite(value):
    assert _validate_filter_settings(_proc(filter_method_protein="at_least_n", filter_mode_protein="overall", filter_min_protein=value))


@pytest.mark.parametrize("field,value", [
    ("width", "typo"), ("width", float("inf")), ("width", -0.1),
    ("width", True), ("down_shift", float("nan")), ("seed", 3.7),
    ("seed", -1), ("seed", 2_147_483_648), ("sample_wise", "maybe"),
])
def test_configured_imputation_values_never_silently_become_defaults(field, value):
    params = {"mode": "numerical", "down_shift": 1.8, "width": 0.3, "seed": 1, "sample_wise": True}
    params[field] = value
    problems = _validate_imputation_settings(_proc(imputation=params))
    assert len(problems) == 1 and f"'{field}' has an invalid value" in problems[0]


def test_valid_imputation_aliases_and_decimal_comma_remain_supported():
    params = {"mode": "quantile", "q": "0,01", "adjustStd": "0,3", "seed": "1.0", "sampleWise": "false"}
    assert _validate_imputation_settings(_proc(imputation=params)) == []
    parsed = viewer_bootstrap._imputation_config({"imputation": params}, "protein")
    assert (parsed.q_value, parsed.adjust_std, parsed.seed, parsed.sample_wise) == (0.01, 0.3, 1, False)
