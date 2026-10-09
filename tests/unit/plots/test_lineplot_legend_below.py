"""The single-feature line plot keeps its width: the legend sits below the axes.

A legend to the right took a fixed share of the width whatever it held, and
long feature names halved the plot. Entries longer than 40 characters are
shortened in the legend only; the table keeps the full name.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.schemas.annotation import AnnotationFilterConfig
from app.services import single_protein_tools
from app.services.annotation_store import reset_all_annotations, save_annotation

LONG = "P12345_S123_long_phosphosite_key_with_many_characters_here"
SAMPLES = [f"S{i}" for i in range(6)]


@pytest.fixture
def annotated():
    rng = np.random.default_rng(0)
    frame = pd.DataFrame({"ProteinNames": [LONG, "SHORT", "MID_1"],
                          **{s: rng.normal(20, 1, 3) for s in SAMPLES}})
    meta = pd.DataFrame({"sample": SAMPLES, "condition": ["A"] * 3 + ["B"] * 3})
    reset_all_annotations()
    save_annotation(kind="protein", source_data=frame, metadata=meta, log2_data=frame, filtered_data=frame,
                    is_log2_transformed=True, metadata_source="manual", filter_config=AnnotationFilterConfig(),
                    auto_detected=False, warnings=[])
    yield
    reset_all_annotations()


def test_the_legend_sits_below_the_axes_with_shortened_names(annotated, monkeypatch) -> None:
    captured: dict = {}
    plt = single_protein_tools._get_plt()
    original = plt.Axes.legend

    def spy(self, *args, **kwargs):
        captured["labels"] = list(args[1])
        captured["loc"] = kwargs.get("loc")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(plt.Axes, "legend", spy)
    png = single_protein_tools.single_protein_lineplot_plot("protein", [LONG, "SHORT", "MID_1"], ["A", "B"])
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert captured["loc"] == "lower center"
    assert "SHORT" in captured["labels"] and "MID_1" in captured["labels"]
    shortened = next(label for label in captured["labels"] if label.startswith("P12345"))
    assert len(shortened) == 40 and shortened.endswith("...") and shortened != LONG
    # The table is untouched by the legend shortening.
    table = single_protein_tools.single_protein_lineplot_table("protein", [LONG], ["A", "B"])
    assert LONG in set(table["Feature"])


@pytest.mark.parametrize("visible", [True, False])
def test_below_plot_legend_respects_advanced_settings(annotated, monkeypatch, visible):
    captured = {}
    def capture(fig, plt, **kwargs):
        legend = fig.axes[0].get_legend()
        captured["legend"] = legend
        plt.close(fig)
        return b"png"
    monkeypatch.setattr(single_protein_tools, "_to_png_bytes", capture)
    single_protein_tools.single_protein_lineplot_plot(
        "protein", ["SHORT"], ["A", "B"],
        advanced={"legendVisible": visible, "legendTitle": "Selected feature", "legendFontSize": 12,
                  "legendTextColor": "#ff0000", "legendFrame": True},
    )
    legend = captured["legend"]
    if not visible:
        assert legend is None
    else:
        assert legend.get_title().get_text() == "Selected feature"
        assert legend.get_texts()[0].get_fontsize() == 12
        assert legend.get_texts()[0].get_color() == "#ff0000"
        assert legend.get_frame_on()
