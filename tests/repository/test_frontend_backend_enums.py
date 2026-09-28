from __future__ import annotations

import re
import sys
import typing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

STATS_PAGE = ROOT / "frontend" / "src" / "features" / "stats" / "StatisticalAnalysisPage.tsx"
STATS_HELPERS = ROOT / "frontend" / "src" / "features" / "stats" / "statsHelpers.ts"
TEST_OPTIONS = ROOT / "frontend" / "src" / "lib" / "statisticalTests.ts"
TYPES_FILE = ROOT / "frontend" / "src" / "lib" / "types.ts"
ANNOTATION_PAGE = ROOT / "frontend" / "src" / "features" / "metadata" / "AnnotationPage.tsx"


def _stats_source() -> str:
    """The statistics section: the page, its panels and their shared helpers."""
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(STATS_PAGE.parent.glob("*.ts*")))


def _block(text: str, start_marker: str, end_marker: str) -> str:
    start = text.index(start_marker)
    return text[start : text.index(end_marker, start)]


def test_ui_test_type_options_match_the_backend() -> None:
    from app.services.functions import _TEST_TYPES

    source = TEST_OPTIONS.read_text(encoding="utf-8")
    block = _block(source, "const TEST_TYPE_OPTIONS", "];")
    offered = set(re.findall(r'value:\s*"([a-z_]+)"', block))
    assert offered == set(_TEST_TYPES), (
        f"UI offers {sorted(offered)}, backend accepts {sorted(_TEST_TYPES)}. "
        "A backend test type that the UI does not offer is unreachable; a UI value "
        "the backend rejects is a runtime error."
    )


def test_persisted_test_type_is_validated_against_the_option_list() -> None:
    source = _stats_source()
    assert 'from "../../lib/statisticalTests"' in source
    assert "TEST_TYPE_VALUES.includes(" in TEST_OPTIONS.read_text(encoding="utf-8"), (
        "restoreTestType must validate against TEST_TYPE_OPTIONS"
    )
    assert 'persisted.testType ?? "unpaired").trim()' not in source, (
        "a hardcoded testType restore has reappeared; it silently drops new values"
    )
    validated_restore_sites = source.count(
        "restoreTestType(persisted.testType)"
    ) + source.count("restoreSimulationTestType(persisted.testType)")
    assert validated_restore_sites == source.count("persisted.testType"), (
        "some testType restore sites bypass a validated option contract"
    )


def test_typescript_test_type_union_matches_the_backend() -> None:
    from app.services.functions import _TEST_TYPES

    source = TYPES_FILE.read_text(encoding="utf-8")
    block = _block(source, "export type StatsTestType", ";")
    declared = set(re.findall(r'"([a-z_]+)"', block))
    assert declared == set(_TEST_TYPES)


def test_ui_cluster_method_options_match_the_backend() -> None:
    from app.schemas.stats import AnovaClusterMethod

    supported = set(typing.get_args(AnovaClusterMethod))
    source = _stats_source()
    block = _block(source, "const ANOVA_CLUSTER_METHOD_OPTIONS", "];")
    offered = set(re.findall(r'value:\s*"([a-z]+)"', block))
    assert offered == supported, (
        f"UI offers {sorted(offered)}, backend accepts {sorted(supported)}. "
        "A backend linkage the UI never offers is unreachable; a UI value the "
        "backend rejects is a runtime error."
    )


def test_typescript_cluster_method_union_matches_the_backend() -> None:
    from app.schemas.stats import AnovaClusterMethod

    supported = set(typing.get_args(AnovaClusterMethod))
    source = TYPES_FILE.read_text(encoding="utf-8")
    block = _block(source, "export type AnovaClusterMethod", ";")
    declared = set(re.findall(r'"([a-z]+)"', block))
    assert declared == supported


def test_persisted_cluster_method_is_validated_against_the_option_list() -> None:
    """A stored value from an older build must not reach scipy unchecked."""
    source = _stats_source()
    assert "ANOVA_CLUSTER_METHOD_VALUES.includes(" in source
    assert source.count("restoreClusterMethod(persisted.clusterMethod)") == 2, (
        "both the ANOVA and the ORA panel must restore the method through the "
        "validated helper"
    )


def test_ora_sends_the_same_cluster_method_it_displays() -> None:
    """ORA rebuilds the clustering; a different linkage renumbers the clusters.

    If the ORA panel resolves a selected cluster without passing the method it
    clustered with, the gene list belongs to a different partition than the one
    the user chose from -- and nothing in the output says so.
    """
    source = _stats_source()
    anova_requests = source.count('postHoc: "none",')
    assert anova_requests >= 1
    block = _block(source, 'source: "anova_cluster"', 'postHoc: "none",')
    assert "clusterMethod," in block, (
        "the ANOVA request ORA builds omits clusterMethod"
    )


def test_ui_normalization_options_are_a_subset_of_the_backend() -> None:
    from app.schemas.annotation import NormalizationMethod

    supported = set(typing.get_args(NormalizationMethod))
    source = ANNOTATION_PAGE.read_text(encoding="utf-8")
    offered = set(re.findall(r'<option value="(none|median|quantile|vsn)"', source))
    assert offered, "the normalization selector should offer options"
    assert offered <= supported, f"UI offers {sorted(offered - supported)} which the backend rejects"
    assert {"none", "median", "quantile"} <= offered


def test_typescript_normalization_union_matches_the_backend() -> None:
    from app.schemas.annotation import NormalizationMethod

    supported = set(typing.get_args(NormalizationMethod))
    source = TYPES_FILE.read_text(encoding="utf-8")
    block = _block(source, "export type NormalizationMethod", ";")
    declared = set(re.findall(r'"([a-z]+)"', block))
    assert declared == supported


@pytest.mark.parametrize("path", [STATS_PAGE, STATS_HELPERS, TEST_OPTIONS, TYPES_FILE, ANNOTATION_PAGE])
def test_referenced_frontend_files_exist(path: Path) -> None:
    assert path.is_file(), f"{path} is missing; update this test if the layout changed"


# --- one data-source vocabulary, in the browser too ---------------------------
#
# The backend collapsed four copies of this Literal into one. The frontend kept
# five hand-written copies of the *old* two-value spelling on its request types,
# and nothing noticed until `tsc` was finally run: a page that let the user pick
# "filtered" could not describe the request it was about to send. These two
# tests make the frontend and backend definitions answerable to each other.


def test_the_frontend_data_source_union_matches_the_backend() -> None:
    from app.schemas.annotation import DataSource as BackendDataSource

    source = TYPES_FILE.read_text(encoding="utf-8")
    match = re.search(r"export type DataSource\s*=\s*([^;]+);", source)
    assert match, "frontend/src/lib/types.ts no longer defines DataSource"
    offered = set(re.findall(r'"([a-z0-9_]+)"', match.group(1)))
    assert offered == set(typing.get_args(BackendDataSource)), (
        f"UI accepts {sorted(offered)}, backend accepts "
        f"{sorted(typing.get_args(BackendDataSource))}"
    )


def test_no_request_type_spells_the_union_by_hand() -> None:
    """Every `dataSource` field must be typed `DataSource`, not a copy of it.

    A narrower hand-written union compiles fine until a selector offers the
    third value, and then fails in a place unrelated to the page that changed.
    """
    offenders = [
        f"{number}: {line.strip()}"
        for number, line in enumerate(
            TYPES_FILE.read_text(encoding="utf-8").splitlines(), start=1
        )
        if re.match(r"\s*dataSource\??:", line) and "DataSource" not in line
    ]
    assert not offenders, offenders


# --- the ladder default has to be reachable ------------------------------------
#
# Every selector opened on "Data" on projects whose backend reported
# `defaultDataSource: "imputed"`. The panels initialised their state with
# `resolveDataSource(persisted.dataSource, null)`, which returns "data" when
# nothing is saved -- and "data" is always available, so the resolver that runs
# once the options arrive kept it. A made-up choice is indistinguishable from a
# real one, and the default became unreachable.

FRONTEND = ROOT / "frontend" / "src"


def test_no_panel_invents_a_data_source_before_the_backend_answers() -> None:
    offenders = []
    for path in sorted(FRONTEND.rglob("*.tsx")) + sorted(FRONTEND.rglob("*.ts")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if "resolveDataSource(" in line and "null)" in line:
                offenders.append(f"{path.relative_to(FRONTEND)}:{number}: {line.strip()}")
    assert not offenders, (
        "resolving against no choices yields 'data', which then looks like a "
        "deliberate selection for ever; start from savedDataSource() instead: "
        f"{offenders}"
    )


def test_the_saved_choice_helper_distinguishes_nothing_from_data() -> None:
    source = (FRONTEND / "lib" / "types.ts").read_text(encoding="utf-8")
    assert "export function savedDataSource(" in source
    assert "): DataSource | null {" in source, (
        "it has to be able to say 'no choice', which is the whole point"
    )


def test_the_default_is_taken_outside_the_state_updater() -> None:
    """React StrictMode runs an updater twice from the same base state.

    A "have we chosen yet" flag flipped inside the updater sends the second pass
    down the other branch, which throws the default away again -- in development
    only, which is where this is looked at.
    """
    hook = (FRONTEND / "lib" / "useDataSourceChoice.ts").read_text(encoding="utf-8")
    body = hook[hook.index("const applyChoices") : hook.index("const chooseDataSource")]
    before, _, inside = body.partition("setDataSource(")
    assert "chosen.current = true;" in before, "the flag must be set before the updater"
    assert "chosen.current = true;" not in inside, "and not inside it"


def test_the_ladder_is_applied_whenever_the_options_arrive() -> None:
    """No panel may decide for itself when the served ladder counts.

    Two did, and both got it backwards. The pathway heatmap applied the choices
    only when imputed was *un*available, so the projects that have an imputed
    matrix never left the placeholder. Single-protein applied them only when the
    response echoed a different source than the one requested -- but the request
    carries the panel's current source, so the echo always matched.
    """
    offenders = []
    for path in sorted(FRONTEND.rglob("*.tsx")):
        lines = path.read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(lines, start=1):
            if "applyDataSourceChoices(" not in line or "=" in line.split("applyDataSourceChoices")[0]:
                continue
            preceding = " ".join(lines[max(0, number - 4) : number - 1])
            if re.search(r"\bif\s*\(", preceding) and "}" not in lines[number - 1]:
                offenders.append(f"{path.relative_to(FRONTEND)}:{number}: {line.strip()}")
    assert not offenders, (
        "the ladder must be applied every time the options arrive; the hook "
        f"already keeps a deliberate choice: {offenders}"
    )
