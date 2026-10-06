"""The viewer routes into the tool's functions; it does not reimplement them.

A viewer project and the tool must produce the same numbers from the same
settings, which only holds if there is one implementation and the viewer merely
routes into it. Several places had quietly grown a second version:

* the imputation source chain, which silently substituted unfiltered log2 data
  when a filter kept nothing -- the shared `choose_best_source` refuses that and
  says so;
* phosphoprotein imputation, which the tool forbids outright and the viewer
  performed anyway;
* the imputation defaults, so a config naming only a mode ran with adjustStd 1.0
  and sampleWise off while the tool used 0.3 and on;
* the samples imputation had to skip, which the tool names and the viewer
  discarded while still reporting the imputation as applied.

These load real viewer projects rather than grepping the source: a rule that is
only asserted as a substring survives any reimplementation spelled differently.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]

from app.schemas.data_tools import ImputationRunRequest
from app.services import viewer_bootstrap
from app.services.annotation_store import get_annotation
from app.services.data_tools import require_imputable_kind
from app.services.functions import choose_best_source
from app.services.viewer_bootstrap import (
    ViewerImputationConfig,
    _imputation_config,
    _normalize_imputation_mode,
    _phosprot_aggregation,
    _unapplied_imputation_info,
    load_viewer_state,
)

REFERENCE_CONFIG = ROOT / "viewer_config.json"

IMPUTATION_PARAMS = (
    ("q_value", "qValue"),
    ("adjust_std", "adjustStd"),
    ("down_shift", "downShift"),
    ("width", "width"),
    ("seed", "seed"),
    ("sample_wise", "sampleWise"),
)


# The tool's standard quantile settings, written out: the viewer refuses an
# imputation mode that does not state its parameters (2026-09-24).
QUANTILE = {"mode": "quantile", "q_value": 0.01, "adjust_std": 0.3, "seed": 1337, "sample_wise": True}


def _project(tmp_path: Path, **package_overrides) -> Path:
    """The shipped reference project, with its dataset package amended.

    Built from the real config so the data files, metadata profile and sample
    names are the ones the tool actually ships, and only the setting under test
    differs.
    """
    config = json.loads(REFERENCE_CONFIG.read_text(encoding="utf-8"))
    name, package = next(iter(config["datasets"].items()))
    package.update(package_overrides)
    config["datasets"] = {name: package}
    # Paths in the reference config are relative to the repository root, so the
    # amended copy has to live there too.
    path = tmp_path / "viewer_config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    rooted = REFERENCE_CONFIG.parent / f".test_{tmp_path.name}_viewer_config.json"
    rooted.write_text(json.dumps(config), encoding="utf-8")
    return rooted


@pytest.fixture
def project(tmp_path):
    made: list[Path] = []

    def build(**overrides) -> Path:
        path = _project(tmp_path, **overrides)
        made.append(path)
        return path

    yield build
    for path in made:
        path.unlink(missing_ok=True)


# --- one implementation ------------------------------------------------------


def test_the_tool_and_the_viewer_share_one_imputation_function() -> None:
    from app.services import data_tools, functions

    assert (
        viewer_bootstrap.impute_values_with_diagnostics
        is functions.impute_values_with_diagnostics
        is data_tools.impute_values_with_diagnostics
    ), "imputation must have exactly one implementation"


def test_the_tool_and_the_viewer_share_one_annotation_function() -> None:
    from app.api import routes_annotations
    from app.services import annotation_processor

    assert (
        viewer_bootstrap.compute_annotation_from_metadata
        is routes_annotations.compute_annotation_from_metadata
        is annotation_processor.compute_annotation_from_metadata
    ), "filtering, log2 and normalization must have one implementation"


# --- an empty filter must not be papered over --------------------------------


def test_a_filter_that_keeps_nothing_fails_the_project_rather_than_unfiltering(
    project,
) -> None:
    """The failure this prevents: a project showing unfiltered values.

    A filter that keeps nothing means the settings are wrong. Substituting the
    unfiltered matrix would hand a collaborator numbers that contradict the
    filter the project reports. Asking for more valid values than there are
    samples is the simplest way to keep nothing.
    """
    config_path = project(
        filter_method_protein="at_least_n",
        filter_min_protein=999,
        filter_mode_protein="per_group",
        imputation=QUANTILE,
    )
    load_viewer_state(config_path)

    annotation = get_annotation("protein")
    assert annotation is not None
    assert annotation.filtered_data.empty, "this filter was supposed to keep nothing"

    said = " ".join(annotation.warnings)
    assert "not be substituted" in said, (
        f"the viewer imputed something after an empty filter, or said nothing: {said}"
    )
    assert annotation.imputed_data.empty, (
        "an empty filter must not yield an imputed matrix built from unfiltered data"
    )
    assert annotation.imputation.applied is False


def test_the_shared_chooser_is_what_refuses_it() -> None:
    """Pins the refusal to the tool's function, not to a viewer-local copy."""
    empty_filtered = pd.DataFrame(columns=["s1", "s2"])
    log2 = pd.DataFrame({"s1": [1.0, 2.0], "s2": [3.0, 4.0]})
    with pytest.raises(ValueError, match="has not been substituted"):
        choose_best_source(empty_filtered, log2, log2)
    assert viewer_bootstrap.choose_best_source is choose_best_source


# --- phosphoprotein ----------------------------------------------------------


def test_the_viewer_refuses_to_impute_phosphoproteins(project) -> None:
    """The tool forbids this outright; the viewer must not do it quietly.

    A phosphoprotein matrix is collapsed from phosphosites, so imputing it
    directly invents protein-level values that no site supports.
    """
    config_path = project(imputation=QUANTILE)
    load_viewer_state(config_path)

    annotation = get_annotation("phosprot")
    assert annotation is not None, "the rest of the project must still load"
    assert annotation.imputation.applied is False
    assert annotation.imputed_data.empty

    said = " ".join(annotation.warnings)
    assert "phosphosite" in said, f"the reason was not reported to the viewer: {said}"
    assert "not be substituted" in said


def test_refusing_one_level_does_not_cost_the_project_the_others(project) -> None:
    config_path = project(imputation=QUANTILE)
    result = load_viewer_state(config_path)

    for kind in ("protein", "phospho"):
        annotation = get_annotation(kind)
        assert annotation is not None, f"{kind} failed to load"
        assert annotation.imputation.applied is True, f"{kind} was not imputed"
    assert not any("bootstrap failed" in w for w in result.warnings), result.warnings


def test_a_project_with_no_imputation_is_not_told_off_about_phosphoproteins(
    project,
) -> None:
    """There is nothing to refuse when nothing was asked for."""
    config_path = project(imputation={"mode": "none"})
    load_viewer_state(config_path)
    annotation = get_annotation("phosprot")
    assert annotation is not None
    assert not any("phosphosite" in w for w in annotation.warnings), annotation.warnings


def test_the_refusal_comes_from_the_tools_own_guard() -> None:
    assert viewer_bootstrap.require_imputable_kind is require_imputable_kind
    with pytest.raises(ValueError, match="phosphosite"):
        require_imputable_kind("phosprot")


# --- invalid settings are rejected before loading ---------------------------


def test_an_out_of_range_seed_is_rejected_before_loading(project, monkeypatch) -> None:
    config_path = project(imputation={**QUANTILE, "seed": -1})
    monkeypatch.setattr(viewer_bootstrap, "set_active_package", lambda *_: pytest.fail("Invalid config changed the active package"))
    with pytest.raises(ValueError, match="'seed' has an invalid value -1"):
        load_viewer_state(config_path)


def test_the_failure_path_never_raises_on_an_unreportable_setting() -> None:
    info = _unapplied_imputation_info(
        ViewerImputationConfig(mode="quantile", seed=-5, q_value=99.0)
    )
    assert info.applied is False
    assert info.mode == "quantile"


def test_an_unknown_imputation_mode_is_refused_and_named() -> None:
    """It used to pass through and be stored as if it were a real method."""
    warnings: list[str] = []
    assert _normalize_imputation_mode("median_of_neighbours", warnings) == "none"
    assert len(warnings) == 1
    assert "median_of_neighbours" in warnings[0]
    assert "quantile" in warnings[0], "the message should name what is valid"


@pytest.mark.parametrize("spelling", ["quantile", "numerical", "perseus", "gaussian"])
def test_the_modes_the_tool_supports_are_still_accepted(spelling: str) -> None:
    assert _normalize_imputation_mode(spelling) in {"quantile", "numerical"}


# --- skipped samples ---------------------------------------------------------


def test_the_viewer_names_the_samples_it_could_not_impute(project, monkeypatch) -> None:
    """A sample with no usable spread keeps its missing values.

    Reporting `applied=True` and nothing else makes that invisible; the tool's
    own route names those samples, so the viewer has to as well.
    """
    from app.services import functions

    real = functions.impute_values_with_diagnostics

    def with_a_skipped_sample(*args, **kwargs):
        diagnostics = real(*args, **kwargs)
        diagnostics.skipped_samples.append("a_flat_sample")
        return diagnostics

    monkeypatch.setattr(
        viewer_bootstrap, "impute_values_with_diagnostics", with_a_skipped_sample
    )
    load_viewer_state(project(imputation=QUANTILE))

    annotation = get_annotation("protein")
    said = " ".join(annotation.warnings)
    assert "a_flat_sample" in said, f"the skipped sample was never mentioned: {said}"
    assert "left unchanged" in said


def test_the_wording_is_the_tools_own() -> None:
    from app.services.data_tools import skipped_sample_warnings

    class _D:
        skipped_samples = ["s1", "s2"]

    (message,) = skipped_sample_warnings(_D())
    assert "s1, s2" in message
    assert skipped_sample_warnings(type("_E", (), {"skipped_samples": []})()) == []


# --- one set of defaults -----------------------------------------------------


@pytest.mark.parametrize("viewer_field,tool_field", IMPUTATION_PARAMS)
def test_the_dataclass_defaults_come_from_the_tools_schema(
    viewer_field: str, tool_field: str
) -> None:
    tool = ImputationRunRequest(kind="protein")
    assert getattr(ViewerImputationConfig(), viewer_field) == getattr(tool, tool_field)


@pytest.mark.parametrize("viewer_field,tool_field", IMPUTATION_PARAMS)
def test_naming_only_a_mode_yields_the_tools_standard_settings(
    viewer_field: str, tool_field: str
) -> None:
    """"Quantile imputation with the standard setting" must mean one thing.

    When a config named none of the accepted spellings, the eagerly-evaluated
    inner default of a chained `.get` was returned and the schema default could
    never apply -- so "standard" meant adjustStd 1.0 and sampleWise off here and
    0.3 and on in the tool.
    """
    resolved = _imputation_config({"imputation": {"mode": "quantile"}}, "protein")
    tool = ImputationRunRequest(kind="protein", method="quantile")
    assert getattr(resolved, viewer_field) == getattr(tool, tool_field)


def test_the_standard_settings_are_what_a_project_actually_runs(project) -> None:
    """End to end, not just at the resolver: the written-out standard block
    resolves to exactly the tool's own request defaults."""
    load_viewer_state(project(imputation=QUANTILE))
    applied = get_annotation("protein").imputation
    tool = ImputationRunRequest(kind="protein")
    assert applied.applied is True
    for _, tool_field in IMPUTATION_PARAMS:
        assert getattr(applied, tool_field) == getattr(tool, tool_field), tool_field


@pytest.mark.parametrize(
    "written,expected_field,expected",
    [
        ({"adjust_std": 0.9}, "adjust_std", 0.9),
        ({"sample_wise": False}, "sample_wise", False),
        ({"q_value": 0}, "q_value", 0.0),
        ({"seed": 0}, "seed", 0),
        ({"width": 0.0}, "width", 0.0),
    ],
)
def test_an_explicit_value_wins_including_a_falsey_one(
    written: dict, expected_field: str, expected
) -> None:
    """Zero and false are answers here, not absences."""
    resolved = _imputation_config({"imputation": {"mode": "quantile", **written}}, "protein")
    assert getattr(resolved, expected_field) == expected


@pytest.mark.parametrize(
    "alias", ["adjust_std", "adjustStd", "adj_std", "variance_modification", "varianceModification"]
)
def test_every_alias_spelling_resolves_to_the_same_value(alias: str) -> None:
    resolved = _imputation_config({"imputation": {"mode": "quantile", alias: 0.7}}, "protein")
    assert resolved.adjust_std == 0.7


def test_a_parameter_written_as_none_falls_back_to_the_default() -> None:
    """The shipped reference config spells unset parameters as the string "none"."""
    resolved = _imputation_config(
        {"imputation": {"mode": "quantile", "adjust_std": "none", "sample_wise": "none"}},
        "protein",
    )
    tool = ImputationRunRequest(kind="protein")
    assert resolved.adjust_std == tool.adjustStd
    assert resolved.sample_wise == tool.sampleWise


@pytest.mark.parametrize("spelling", ["phosprot", "phosphoprotein"])
def test_a_per_level_override_is_read_under_either_spelling(spelling: str) -> None:
    """`filter_*` and `log2_transform_*` say "phosphoprotein" in the same file."""
    resolved = _imputation_config(
        {"imputation": {"mode": "none", spelling: {"mode": "numerical"}}}, "phosprot"
    )
    assert resolved.mode == "numerical"


# --- "none" means not provided, everywhere -----------------------------------


def test_collapse_mode_none_is_absence_not_a_typo() -> None:
    """A protein-only project says "none"; that must not read as a bad value."""
    warnings: list[str] = []
    assert _phosprot_aggregation({"collapse_mode": "none"}, warnings) is None
    assert warnings == [], warnings


def test_a_refused_imputation_is_not_described_as_if_it_had_run(project) -> None:
    """The report must not explain settings that produced nothing.

    The annotation keeps the mode after a refusal so the refusal itself can be
    reported. The report's imputation prose keys off the mode, so without the
    `applied` check a phosphoprotein project would tell a collaborator its values
    had been imputed with settings that were never used.
    """
    from app.services.report_function import _imputation_paragraphs

    load_viewer_state(project(imputation=QUANTILE))

    refused = get_annotation("phosprot")
    assert refused.imputation.mode == "quantile"
    assert refused.imputation.applied is False
    assert _imputation_paragraphs("phosprot") in ([], ""), (
        "a refused imputation was described as if it had run"
    )

    applied = get_annotation("protein")
    assert applied.imputation.applied is True
    assert _imputation_paragraphs("protein"), "a real imputation must still be described"
