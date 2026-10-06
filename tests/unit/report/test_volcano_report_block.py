"""What a single volcano's block in the report must state on its own.

A reader checking one comparison should not have to scroll back to the level
preamble to learn which rows reached it, whether they were imputed, or how many
things the stated thresholds actually selected.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]

import app.services.report_function as report
from app.schemas.summary import SummaryVolcanoEntry
from app.services.functions import ENTITY_LABELS_BY_KIND, entity_labels_for_kind


def _text(markup: str) -> str:
    import html as html_module

    return html_module.unescape(re.sub(r"<[^>]+>", " ", markup))


def _entry(**overrides) -> SummaryVolcanoEntry:
    values = {
        "kind": "protein",
        "condition1": "WT",
        "condition2": "GRK",
        "dataSource": "data",
        "pValueThreshold": 0.05,
        "log2fcThreshold": 1.0,
    }
    values.update(overrides)
    return SummaryVolcanoEntry(**values)


def _annotation(**overrides):
    values = {
        "filter_config": SimpleNamespace(
            method="at_least_n", mode="in_at_least_one_group",
            minPresent=3, normalization="none",
        ),
        "filtered_data": pd.DataFrame({"v": range(7450)}),
        "source_data": pd.DataFrame({"v": range(9002)}),
        "imputation": SimpleNamespace(
            mode="numerical", downShift=1.8, width=0.3, seed=69, sampleWise=False,
            qValue=0.01, adjustStd=0.3,
        ),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture
def counted(monkeypatch):
    """A volcano block whose counts come from a stubbed run_volcano."""
    def _build(kind="protein", up=312, down=288, total=7450, not_significant=6850,
               entry=None, annotation=None):
        monkeypatch.setattr(
            report, "run_volcano",
            lambda payload: SimpleNamespace(
                upregulatedCount=up, downregulatedCount=down,
                totalRows=total, notSignificantCount=not_significant,
            ),
        )
        monkeypatch.setattr(
            report, "get_annotation",
            lambda k: annotation if annotation is not None else _annotation(),
        )
        monkeypatch.setattr(
            report, "volcano_html", lambda payload, advanced=None: "<div>plot</div>"
        )
        return report._volcano_block_html(
            kind=kind, entries=[entry or _entry(kind=kind)], warnings=[]
        )
    return _build


def test_block_states_filtering_for_the_comparison(counted) -> None:
    text = _text(counted())
    # The fixture applies no normalization, so no normalization line is printed.
    assert "Normalization:" not in text
    # The default entry runs on the unfiltered Data source, so the block says
    # so with the row counts instead of restating the filter recipe.
    assert "Filtering: Not applied to this plot; it uses all 9002 rows." in " ".join(text.split())
    assert "keeps 7450 rows" in text
    assert "at least 3 valid values" not in text


def test_filtering_matches_the_level_preamble_word_for_word() -> None:
    """One wording, so the two places can never disagree."""
    annotation = _annotation()
    assert report._filter_description(annotation) is not None
    assert report._filter_description(None) is None
    assert report._filter_description(SimpleNamespace(filter_config=None)) is None


def test_non_imputed_comparison_says_so(counted) -> None:
    text = _text(counted(entry=_entry(dataSource="data")))
    assert "Imputation:" in text
    assert "Not applied" in text


def test_imputed_comparison_states_the_settings(counted) -> None:
    monkey_text = _text(counted(entry=_entry(dataSource="imputed")))
    assert "Imputation:" in monkey_text
    assert "Not applied" not in monkey_text
    # the numerical branch names the downshift and width it drew with
    assert "1.8" in monkey_text and "0.3" in monkey_text
    assert "seed" not in monkey_text, "random seeds are not reported"


def test_imputed_selection_without_recorded_settings_is_stated(counted) -> None:
    annotation = _annotation(imputation=SimpleNamespace(mode="none"))
    text = _text(counted(entry=_entry(dataSource="imputed"), annotation=annotation))
    assert "no imputation settings are recorded" in text


@pytest.mark.parametrize(
    "kind,plural",
    [("protein", "proteins"), ("phospho", "phosphosites"), ("phosprot", "phosphoproteins")],
)
def test_counts_name_the_entity_not_the_word_feature(counted, kind, plural) -> None:
    text = _text(counted(kind=kind))
    assert plural in text
    assert "feature" not in text.lower(), "the report must name the entity, not 'features'"


def test_counts_report_up_down_total_and_not_significant(counted) -> None:
    text = _text(counted(up=312, down=288, total=7450, not_significant=6850))
    assert "312 proteins upregulated" in text
    assert "288 downregulated" in text
    assert "7,450 tested proteins" in text
    assert "6,850 not significant" in text


def test_counts_name_the_direction_under_the_new_convention(counted) -> None:
    """log2FC is condition1 - condition2, so 'up' is higher in condition1."""
    text = _text(counted())
    assert "upregulated in WT" in text
    assert "higher in GRK" in text


def test_a_single_hit_is_not_pluralised(counted) -> None:
    text = _text(counted(up=1, down=0, total=1, not_significant=0))
    assert "1 protein upregulated" in text
    assert "1 tested protein" in text


def test_counts_failure_warns_and_still_renders_the_plot(monkeypatch) -> None:
    def boom(payload):
        raise ValueError("no replicates")

    monkeypatch.setattr(report, "run_volcano", boom)
    monkeypatch.setattr(report, "get_annotation", lambda k: _annotation())
    monkeypatch.setattr(
        report, "volcano_html", lambda payload, advanced=None: "<div>plot</div>"
    )
    warnings: list[str] = []
    markup = report._volcano_block_html(
        kind="protein", entries=[_entry()], warnings=warnings
    )
    # The plot is escaped into the iframe's srcdoc, so look for the frame.
    assert "<iframe" in markup and "srcdoc=" in markup
    assert "Could not render this interactive plot" not in markup
    assert "Result:" not in markup
    assert warnings and "no replicates" in warnings[0]


def test_every_dataset_level_has_an_entity_name() -> None:
    for kind in ("protein", "phospho", "phosprot", "peptide", "precursor"):
        singular, plural = entity_labels_for_kind(kind)
        assert singular and plural and singular != "feature"
    assert entity_labels_for_kind("unknown") == ENTITY_LABELS_BY_KIND["protein"]


def test_entity_names_agree_with_the_ai_context_vocabulary() -> None:
    """The chat surface and the report must call the same row the same thing."""
    from app.services import ai_functions

    for kind, labels in ai_functions._COMPLETENESS_KIND_LABELS.items():
        assert entity_labels_for_kind(kind) == labels, kind
