from __future__ import annotations

import re
import sys
import typing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

STATS_PAGE = ROOT / "frontend" / "src" / "features" / "stats" / "StatisticalAnalysisPage.tsx"
TYPES_FILE = ROOT / "frontend" / "src" / "lib" / "types.ts"
ANNOTATION_PAGE = ROOT / "frontend" / "src" / "features" / "metadata" / "AnnotationPage.tsx"


def _block(text: str, start_marker: str, end_marker: str) -> str:
    start = text.index(start_marker)
    return text[start : text.index(end_marker, start)]


def test_ui_test_type_options_match_the_backend() -> None:
    from app.services.functions import _TEST_TYPES

    source = STATS_PAGE.read_text(encoding="utf-8")
    block = _block(source, "const TEST_TYPE_OPTIONS", "];")
    offered = set(re.findall(r'value:\s*"([a-z_]+)"', block))
    assert offered == set(_TEST_TYPES), (
        f"UI offers {sorted(offered)}, backend accepts {sorted(_TEST_TYPES)}. "
        "A backend test type that the UI does not offer is unreachable; a UI value "
        "the backend rejects is a runtime error."
    )


def test_persisted_test_type_is_validated_against_the_option_list() -> None:
    source = STATS_PAGE.read_text(encoding="utf-8")
    assert "TEST_TYPE_VALUES.includes(" in source, (
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


@pytest.mark.parametrize("path", [STATS_PAGE, TYPES_FILE, ANNOTATION_PAGE])
def test_referenced_frontend_files_exist(path: Path) -> None:
    assert path.is_file(), f"{path} is missing; update this test if the layout changed"
