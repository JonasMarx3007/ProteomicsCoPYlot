"""What the missed-cleavage figure says, and under which rule it says it.

Two separate ways of misreporting the same digest:

* The number written on each bar is the one quoted when a digest is assessed --
  the share of sequences with *at least one* missed cleavage. It used to be the
  share of the single `Count == 1` class, which is a smaller number, and the
  gap grows exactly where it matters: a sample whose peptides carry two or three
  missed cleavages looked *cleaner* than one carrying one each.
* The page offers a `Cleavage Rule`, and the summary report saved it and then
  rendered under trypsin regardless -- and titled the figure "Trypsin", so the
  report stated a rule the reader had not chosen.
"""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]

import app.services.peptide_tools as pt
import app.services.report_function as report
from app.schemas.summary import SummaryReportContext, SummaryReportRequest

# One sample's worth of sequences, with a known missed-cleavage profile under
# trypsin: a C-terminal K is the expected cut, an internal K/R is a miss.
SEQUENCES = {
    "PEPTIDEK": 0,
    "AAAKAAAR": 1,
    "AAKAARAAR": 2,
    "GGKGGRGGKGGR": 3,
}
RUNS = ["run_1.raw", "run_2.raw"]


def test_the_planted_profile_is_what_the_counter_sees() -> None:
    """The fixture is only useful if these really are 0, 1, 2 and 3."""
    for sequence, expected in SEQUENCES.items():
        assert pt.count_missed_cleavages(sequence, "trypsin") == expected


def _peptide_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "File.Name": run,
                "Modified.Sequence": sequence,
                "Stripped.Sequence": sequence,
                "Precursor.Quantity": 1000.0,
            }
            for run in RUNS
            for sequence in SEQUENCES
        ]
    )


def _rendered_bar_texts(**kwargs) -> list[str]:
    """The strings `peptide_missed_cleavage_plot` writes onto its bars."""
    frame = _peptide_frame()
    metadata = pd.DataFrame({"sample": RUNS, "condition": ["ctrl", "treat"]})
    captured: dict[str, object] = {}

    def capture(fig, plt, **_kwargs) -> bytes:
        captured["texts"] = [text.get_text() for text in fig.axes[0].texts]
        captured["text_y"] = [float(text.get_position()[1]) for text in fig.axes[0].texts]
        captured["title"] = fig.axes[0].get_title()
        plt.close(fig)
        return b"png"

    with ExitStack() as stack:
        stack.enter_context(patch.object(pt, "get_peptide_frame", return_value=frame))
        stack.enter_context(
            patch.object(pt, "get_peptide_metadata", return_value=SimpleNamespace(frame=metadata, empty=False))
        )
        stack.enter_context(patch.object(pt, "get_current_dataset", return_value=None))
        stack.enter_context(patch.object(pt, "_to_png_bytes", capture))
        pt.peptide_missed_cleavage_plot(**kwargs)

    assert captured["title"], "the figure lost its title"
    _rendered_bar_texts.last_y = list(captured["text_y"])  # type: ignore[attr-defined]
    return list(captured["texts"])  # type: ignore[arg-type]


def test_the_bar_text_sits_at_the_break_above_the_zero_class() -> None:
    """One sequence in four has no missed cleavage, so the 0-class bar ends at 25 %; the label
    is written just above that break, inside the first missed-cleavage class (2026-10-14)."""
    _rendered_bar_texts()
    ys = _rendered_bar_texts.last_y  # type: ignore[attr-defined]
    assert ys and all(25.0 < y < 30.0 for y in ys), ys


def test_the_bar_text_is_the_share_with_at_least_one_missed_cleavage() -> None:
    """Three of the four sequences carry a miss, so every bar reads 75.0%.

    The `Count == 1` class is one sequence in four. A renderer that still prints
    that class alone reads 25.0% here.
    """
    texts = _rendered_bar_texts()
    assert texts == ["75.0%", "75.0%"], texts


def test_the_bar_text_keeps_one_decimal() -> None:
    assert all(text.count(".") == 1 and text.endswith("%") for text in _rendered_bar_texts())


def test_no_text_is_written_when_the_toggle_is_off() -> None:
    assert _rendered_bar_texts(text=False) == []


# --- the report renders under the rule the page used --------------------------


def _report_missed_cleavage_call(monkeypatch: pytest.MonkeyPatch, settings: dict) -> dict:
    received: dict[str, object] = {}

    def capture(**kwargs: object) -> bytes:
        received.update(kwargs)
        return b"png"

    monkeypatch.setattr(report, "peptide_missed_cleavage_plot", capture)
    for name in (
        "qc_peptide_coverage_plot",
        "completeness_missing_value_plot_peptide",
        "peptide_rt_plot",
        "peptide_modification_plot",
    ):
        monkeypatch.setattr(report, name, lambda *args, **kwargs: b"png")
    monkeypatch.setattr(report, "get_annotation", lambda kind: None)
    monkeypatch.setattr(
        report, "get_current_dataset", lambda kind: object() if kind == "peptide" else None
    )

    context = SummaryReportContext(qcSettings={"peptide": {"missedCleavage": settings}})
    report.report_function(
        SummaryReportRequest(title="T", author="A", reportContext=context)
    )
    assert received, "the report never rendered the missed cleavage figure"
    return received


@pytest.mark.parametrize(
    ("saved", "expected"),
    [
        ({"protease": "trypsin_lysc"}, "trypsin_lysc"),
        ({"protease": "trypsin"}, "trypsin"),
        # Nothing saved is the page's own default, not a silent second rule.
        ({}, "trypsin"),
        ({"protease": "   "}, "trypsin"),
    ],
)
def test_the_report_renders_under_the_saved_cleavage_rule(
    monkeypatch: pytest.MonkeyPatch, saved: dict, expected: str
) -> None:
    received = _report_missed_cleavage_call(monkeypatch, saved)
    assert received["protease"] == expected


def test_the_report_figure_title_states_the_saved_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    """The renderer names the rule in its title, so passing it fixes both."""
    received = _report_missed_cleavage_call(monkeypatch, {"protease": "trypsin_lysc"})
    assert pt.PROTEASE_LABELS[received["protease"]] == "Trypsin / Lys-C"
