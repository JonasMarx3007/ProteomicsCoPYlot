"""Two strings that must follow something else rather than be typed again.

* The summary report prints a version. Held as its own literal in the report
  builder, it printed whatever was typed there, which is only right until the
  application is released again -- and a report is the artefact a reader dates
  the analysis by.
* The Kinase Library download's suggested file name spells out the contrast. Written by
  hand it said `(cond2 - ctrl2) - (cond1 - ctrl1)` while the exported log2FC is
  the other way round, so a saved file claimed the opposite sign to the numbers
  inside it.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]

from app.app_version import APP_VERSION
from app.services import report_function
from app.services.functions import comparison_contrast



# --- the report prints the application's version ------------------------------


def test_the_report_version_is_the_application_version() -> None:
    assert APP_VERSION in report_function.VERSION
    assert report_function.VERSION == f"Proteomics CoPYlot V{APP_VERSION}"


def test_the_report_builder_holds_no_version_literal_of_its_own(monkeypatch: pytest.MonkeyPatch) -> None:
    """A second copy is a second thing to forget on the next release.

    The application's version is changed and the report builder loaded again:
    a version the builder spelled out itself would not follow.
    """
    import importlib

    import app.app_version

    monkeypatch.setattr(app.app_version, "APP_VERSION", "99.98.97")
    try:
        importlib.reload(report_function)
        assert report_function.VERSION == "Proteomics CoPYlot V99.98.97"
    finally:
        monkeypatch.undo()
        importlib.reload(report_function)
    assert report_function.VERSION == f"Proteomics CoPYlot V{APP_VERSION}"


def test_the_printed_report_carries_that_version(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.schemas.summary import SummaryReportRequest

    monkeypatch.setattr(report_function, "get_annotation", lambda kind: None)
    monkeypatch.setattr(report_function, "get_current_dataset", lambda kind: None)
    html = report_function.report_function(
        SummaryReportRequest(title="T", author="A")
    ).html
    assert f"Proteomics CoPYlot V{APP_VERSION}" in html


# --- the Kinase Library file name matches the arithmetic in the file --------------------


CONTRAST_FIXTURE = ROOT / "tests" / "fixtures" / "comparison_contrast.json"


def test_the_contrast_is_the_one_the_ksea_file_name_is_held_to() -> None:
    """The orientation the Kinase Library file name must spell out.

    frontend/tests/unit/ksea-filename.test.tsx mounts the page and holds its
    control-volcano file name to the same fixture, so the name cannot drift
    from `comparison_contrast`.
    """
    import json

    fixture = json.loads(CONTRAST_FIXTURE.read_text(encoding="utf-8"))
    contrast = comparison_contrast(
        fixture["condition1"], fixture["condition2"], fixture["condition1Control"], fixture["condition2Control"]
    )
    assert contrast == fixture["contrast"]
    # Condition 1 is the minuend.
    assert contrast.startswith(f"({fixture['condition1']} - ")


def test_the_exported_log2fc_is_the_control_volcano_number_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Which is what fixes the orientation: Kinase Library re-exports, it does not re-sign.

    `run_volcano_control` computes (condition1 - its control) - (condition2 -
    its control); that orientation is pinned by
    test_contrast_label_matches_computation.py. This shows the Kinase Library table hands
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
                    "selected_pval": 0.01,
                    "significance": "Upregulated",
                    "neg_log10_selected_pval": 2.0,
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
    assert float(table["log2FC"].iloc[0]) == 4.0, "Kinase Library flipped the sign on the way out"
