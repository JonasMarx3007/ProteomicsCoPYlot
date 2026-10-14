"""The coverage plot names its total line, counts stand on the bars, summary says "per condition".

The dashed total used to be an unlabelled red line; the summary title still
read "per sample" over condition means; and the count labels were printed on
the coloured bar faces. The legend entry can be dropped from the advanced
panel (`referenceLineLegend: false`) without losing the line.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.schemas.annotation import AnnotationFilterConfig
from app.services import plot_images
from app.services.annotation_store import reset_all_annotations, save_annotation

SAMPLES = [f"{group}{i}" for group in "AB" for i in range(1, 4)]


@pytest.fixture
def annotated():
    rng = np.random.default_rng(0)
    frame = pd.DataFrame({"ProteinNames": [f"P{i}" for i in range(50)]})
    for sample in SAMPLES:
        values = rng.normal(20, 1, 50)
        values[rng.random(50) < 0.2] = np.nan
        frame[sample] = values
    meta = pd.DataFrame({"sample": SAMPLES, "condition": [s[0] for s in SAMPLES]})
    reset_all_annotations()
    save_annotation(kind="protein", source_data=frame, metadata=meta, log2_data=frame, filtered_data=frame,
                    is_log2_transformed=True, metadata_source="manual", filter_config=AnnotationFilterConfig(),
                    auto_detected=False, warnings=[])
    yield frame
    reset_all_annotations()


def _capture(monkeypatch):
    """Keep the figure instead of its PNG bytes."""
    captured = {}

    def keep(fig, plt, **kwargs):
        captured["fig"] = fig
        return b"\x89PNG"

    monkeypatch.setattr(plot_images, "_to_png_bytes", keep)
    return captured


def test_the_total_line_is_named_first_in_the_legend(annotated, monkeypatch) -> None:
    captured = _capture(monkeypatch)
    plot_images.qc_coverage_plot("protein", text=True)
    ax = captured["fig"].axes[0]
    labels = [t.get_text() for t in ax.get_legend().get_texts()]
    assert labels == ["Total", "A", "B"]  # "Total", first (2026-10-14)
    assert ax.get_title() == "Proteins per sample"
    # Count labels start at the bar top, not on the bar face.
    bars = [patch for patch in ax.patches if patch.get_height() > 0]
    texts = [t for t in ax.texts if t.get_text().strip().isdigit()]
    assert len(texts) == len(bars)
    assert all(t.get_position()[1] == pytest.approx(bar.get_height()) for t, bar in zip(texts, bars))


def test_summary_mode_names_conditions_and_keeps_only_the_line_entry(annotated, monkeypatch) -> None:
    captured = _capture(monkeypatch)
    plot_images.qc_coverage_plot("protein", summary=True)
    ax = captured["fig"].axes[0]
    assert ax.get_title() == "Proteins per condition"
    labels = [t.get_text() for t in ax.get_legend().get_texts()]
    assert len(labels) == 1 and labels[0] == "Total"


def test_the_panel_can_drop_the_entry_and_keep_the_line(annotated, monkeypatch) -> None:
    captured = _capture(monkeypatch)
    plot_images.qc_coverage_plot("protein", summary=True, advanced={"referenceLineLegend": False})
    ax = captured["fig"].axes[0]
    assert ax.get_legend() is None
    assert any(line.get_linestyle() == "--" for line in ax.lines)
    plot_images.qc_coverage_plot("protein", advanced={"referenceLineLegend": False})
    ax = captured["fig"].axes[0]
    assert [t.get_text() for t in ax.get_legend().get_texts()] == ["A", "B"]
