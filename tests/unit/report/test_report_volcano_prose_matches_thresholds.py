"""The general volcano prose must not contradict the thresholds a comparison used.

The report used to open every volcano section with fixed sentences claiming an
FDR of 0.05, a fold change of > 2 and dotted threshold lines, whatever the
comparison below had actually been run with. The prose now names those values
only as the commonly used defaults, points at the per-comparison Statistics
line for the values applied, and the paired test is described as what it is.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

import app.services.report_function as report
from app.schemas.summary import SummaryVolcanoEntry

COMMENTS = json.loads((ROOT / "data" / "report" / "report_general_comments.json").read_text(encoding="utf-8"))


def _text(markup: str) -> str:
    import html as html_module

    return html_module.unescape(re.sub(r"<[^>]+>", " ", markup))


def test_general_volcano_prose_states_defaults_only_as_defaults() -> None:
    for key in ("VolcanoProt", "VolcanoPhos"):
        paragraphs = COMMENTS[key]
        joined = " ".join(paragraphs)
        # Numbers appear once, in the sentence that calls them defaults and
        # defers to the Statistics line.
        numbered = [p for p in paragraphs if "0.05" in p or "> 1" in p]
        assert len(numbered) == 1, key
        assert "Commonly used settings" in numbered[0]
        assert "Statistics line" in numbered[0]
        assert "may differ" in numbered[0]
        # Claims the code does not honour are gone.
        assert "FC > 2" not in joined and "fold change of > 2" not in joined
        assert "dotted" not in joined
        assert "was set to 0.05" not in joined
        # The plot conventions the code does honour are stated.
        assert "first condition minus second" in joined
        assert "raw p-value when uncorrected" in joined


def test_statistics_line_carries_the_values_actually_used() -> None:
    entry = SummaryVolcanoEntry(
        kind="protein", condition1="WT", condition2="GRK", dataSource="data",
        pValueThreshold=0.01, log2fcThreshold=0.5, testType="paired", useUncorrected=True,
    )
    line = _text(report._volcano_statistics_html(entry))
    assert "p < 0.01" in line
    assert "|log2 fold change| > 0.5" in line
    assert "uncorrected p-values" in line
    assert "paired t-test (on within-pair differences)" in line
    assert "pooled" not in line


def test_paired_label_is_not_called_pooled() -> None:
    assert report._TEST_TYPE_REPORT_LABELS["paired"] == "paired t-test (on within-pair differences)"
    assert "pooled" in report._TEST_TYPE_REPORT_LABELS["unpaired"]
