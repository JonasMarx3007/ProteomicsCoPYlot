"""Two strings that must follow something else rather than be typed again.

* The summary report prints a version. Held as its own literal in the report
  builder, it printed whatever was typed there, which is only right until the
  application is released again -- and a report is the artefact a reader dates
  the analysis by.
* The KSEA download's suggested file name spells out the contrast. Written by
  hand it said `(cond2 - ctrl2) - (cond1 - ctrl1)` while the exported log2FC is
  the other way round, so a saved file claimed the opposite sign to the numbers
  inside it.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.app_version import APP_VERSION
from app.services import report_function
from app.services.functions import comparison_contrast

KSEA_PAGE = ROOT / "frontend" / "src" / "features" / "phospho" / "KseaPage.tsx"


# --- the report prints the application's version ------------------------------


def test_the_report_version_is_the_application_version() -> None:
    assert APP_VERSION in report_function.VERSION
    assert report_function.VERSION == f"Proteomics CoPYlot V{APP_VERSION}"


def test_the_report_builder_holds_no_version_literal_of_its_own() -> None:
    """A second copy is a second thing to forget on the next release."""
    source = report_function.__file__
    text = Path(source).read_text(encoding="utf-8")
    literals = re.findall(r"[\"']Proteomics CoPYlot V\d+\.\d+\.\d+[\"']", text)
    assert not literals, f"a hard-coded version string is back: {literals}"


def test_the_printed_report_carries_that_version(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.schemas.summary import SummaryReportRequest

    monkeypatch.setattr(report_function, "get_annotation", lambda kind: None)
    monkeypatch.setattr(report_function, "get_current_dataset", lambda kind: None)
    html = report_function.report_function(
        SummaryReportRequest(title="T", author="A")
    ).html
    assert f"Proteomics CoPYlot V{APP_VERSION}" in html


# --- the KSEA file name matches the arithmetic in the file --------------------


def _control_filename_template() -> str:
    text = KSEA_PAGE.read_text(encoding="utf-8")
    # The four tokens must still be bound to the conditions this test assumes,
    # or swapping two `const` lines would slip past the check below.
    for name, source in (
        ("c1", "condition1"),
        ("c2", "condition2"),
        ("c1Ctrl", "condition1Control"),
        ("c2Ctrl", "condition2Control"),
    ):
        assert f"const {name} = toFilenameToken({source});" in text, (
            f"{name} is no longer the filename token for {source}"
        )
    match = re.search(r"return `([^`]*_minus_[^`]*)`;", text)
    assert match, "the control-volcano KSEA file name no longer spells out a contrast"
    return match.group(1)


def test_the_ksea_control_file_name_states_the_contrast_that_was_exported() -> None:
    """Derived from `comparison_contrast`, so the name cannot drift from it."""
    contrast = comparison_contrast("${c1}", "${c2}", "${c1Ctrl}", "${c2Ctrl}")
    expected = contrast.replace(" - ", "-").replace(")-(", ")_minus_(")
    assert _control_filename_template() == expected


def test_the_reversed_file_name_is_gone() -> None:
    reversed_contrast = comparison_contrast("${c2}", "${c1}", "${c2Ctrl}", "${c1Ctrl}")
    reversed_name = reversed_contrast.replace(" - ", "-").replace(")-(", ")_minus_(")
    assert _control_filename_template() != reversed_name


def test_the_exported_log2fc_is_the_control_volcano_number_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Which is what fixes the orientation: KSEA re-exports, it does not re-sign.

    `run_volcano_control` computes (condition1 - its control) - (condition2 -
    its control); that orientation is pinned by
    test_contrast_label_matches_computation.py. This shows the KSEA table hands
    those numbers on untouched, so the file name has to say the same thing.
    """
    from app.services import phospho_tools, stats_tools

    seen: dict[str, object] = {}

    def fake_run(payload):
        seen["condition1"] = payload.condition1
        seen["condition2"] = payload.condition2
        seen["condition1Control"] = payload.condition1Control
        seen["condition2Control"] = payload.condition2Control
        return SimpleNamespace(
            rows=[
                {
                    "UPD_seq": "AAAAAAAs*AAAAAAA",
                    "log2FC": 4.0,
                    "pval": 0.001,
                    "adj_pval": 0.01,
                    "significance": "Upregulated",
                    "neg_log10_adj_pval": 2.0,
                }
            ]
        )

    monkeypatch.setattr(stats_tools, "run_volcano_control", fake_run)
    table = phospho_tools.ksea_table(
        condition1="A",
        condition2="B",
        source="volcano_control",
        condition1_control="C",
        condition2_control="D",
    )
    assert seen == {
        "condition1": "A",
        "condition2": "B",
        "condition1Control": "C",
        "condition2Control": "D",
    }
    assert float(table["log2FC"].iloc[0]) == 4.0, "KSEA flipped the sign on the way out"
