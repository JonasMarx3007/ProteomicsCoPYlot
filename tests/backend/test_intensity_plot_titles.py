"""Titles say what the values are: condition means, not measured values.

The intensity histogram and the boxplot's Mean mode average each feature over
a condition's replicates before drawing; "measured intensity" was the title of
both, the same words Single mode uses for one sample's actual values.
"""

from __future__ import annotations

import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from app.services import plot_images  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ["A1", "A2", "B1", "B2"]


@pytest.fixture
def captured(monkeypatch):
    frame = pd.DataFrame({"ProteinNames": [f"P{i}" for i in range(6)], **{s: np.random.default_rng(i).normal(20, 1, 6) for i, s in enumerate(SAMPLES)}})
    meta = pd.DataFrame({"sample": SAMPLES, "condition": ["A", "A", "B", "B"]})
    monkeypatch.setattr(plot_images, "log2_qc_frame", lambda kind: frame)
    monkeypatch.setattr(plot_images, "_get_sample_columns", lambda kind, df: SAMPLES)
    monkeypatch.setattr(plot_images, "_metadata_for_kind", lambda kind, df, cols: meta.copy())
    figures = []
    monkeypatch.setattr(plot_images, "_to_png_bytes", lambda fig, plt, **kw: figures.append(fig) or b"")
    return figures


def _title(figures):
    return figures[-1].axes[0].get_title()


def test_boxplot_mean_mode_is_titled_as_condition_means(captured):
    plot_images.qc_boxplot_plot(kind="protein", mode="Mean")
    assert _title(captured) == "Mean intensity per condition (log2)"


def test_boxplot_single_mode_keeps_measured_values(captured):
    plot_images.qc_boxplot_plot(kind="protein", mode="Single")
    assert _title(captured) == "Measured intensity values (log2)"


def test_histogram_is_titled_as_condition_means(captured):
    plot_images.qc_intensity_histogram_plot(kind="protein")
    assert _title(captured) == "Distribution of mean intensity per condition (log2)"


def test_the_three_pipelines_use_the_same_titles():
    pip = (ROOT / "proteomicscopylot" / "notebook_functions.py").read_text(encoding="utf-8")
    r = (ROOT / "proteomicscopylot" / "notebook_functions.R").read_text(encoding="utf-8")
    for title in ("Distribution of mean intensity per condition (log2)", "Mean intensity per condition (log2)"):
        assert title in pip and title in r, title
    assert not re.search(r"measured intensity \(log2\)", pip, re.I) and not re.search(r"measured intensity \(log2\)", r, re.I)


def test_median_labels_sit_above_the_line_for_zero_and_negative_medians(monkeypatch):
    """Centred data: the label must not land on or below the median line."""
    frame = pd.DataFrame({"Phosphoprotein": [f"P{i}" for i in range(20)],
                          **{s: np.linspace(-2.0, -1.0, 20) + 0.1 * i for i, s in enumerate(SAMPLES)}})
    meta = pd.DataFrame({"sample": SAMPLES, "condition": ["A", "A", "B", "B"]})
    monkeypatch.setattr(plot_images, "log2_qc_frame", lambda kind: frame)
    monkeypatch.setattr(plot_images, "_get_sample_columns", lambda kind, df: SAMPLES)
    monkeypatch.setattr(plot_images, "_metadata_for_kind", lambda kind, df, cols: meta.copy())
    figures = []
    monkeypatch.setattr(plot_images, "_to_png_bytes", lambda fig, plt, **kw: figures.append(fig) or b"")
    for mode in ("Mean", "Single"):
        plot_images.qc_boxplot_plot(kind="phosprot", mode=mode, text=True)
        ax = figures[-1].axes[0]
        labels = [t for t in ax.texts if t.get_text().replace("-", "").replace(".", "").isdigit()]
        assert labels, mode
        low, high = ax.get_ylim()
        for label in labels:
            value = float(label.get_text())
            assert value < 0
            assert label.get_position()[1] == pytest.approx(value + 0.02 * (high - low), abs=1e-6), mode
            assert label.get_position()[1] > value


@pytest.mark.parametrize("column,label", [("ProteinNames", "Proteins"), ("PTM_Collapse_key", "Phosphosites"), ("Phosphoprotein", "Phosphoproteins")])
def test_missing_value_heatmap_names_its_rows_by_level(monkeypatch, column, label):
    from app.services import completeness_tools

    frame = pd.DataFrame({column: ["x", "y"], "A1": [1.0, np.nan], "A2": [2.0, 2.0], "B1": [np.nan, 3.0], "B2": [4.0, 4.0]})
    meta = pd.DataFrame({"sample": SAMPLES, "condition": ["A", "A", "B", "B"]})
    monkeypatch.setattr(completeness_tools, "_frame_and_meta", lambda kind: (frame, meta))
    figures = []
    monkeypatch.setattr(completeness_tools, "_to_png_bytes", lambda fig, plt, **kw: figures.append(fig) or b"")
    completeness_tools.completeness_missing_value_heatmap("protein")
    assert figures[-1].axes[0].get_ylabel() == label


def test_pip_and_r_heatmaps_name_their_rows_by_level():
    pip = (ROOT / "proteomicscopylot" / "notebook_functions.py").read_text(encoding="utf-8")
    r = (ROOT / "proteomicscopylot" / "notebook_functions.R").read_text(encoding="utf-8")
    assert "Protein Numbers" not in pip and "Protein Numbers" not in r
    for text in (pip, r):
        for label in ("Phosphoproteins", "Phosphosites", "Proteins"):
            assert f'"{label}"' in text


def test_per_sample_coverage_plots_label_their_axis_sample(monkeypatch):
    frame = pd.DataFrame({"ProteinNames": [f"P{i}" for i in range(6)], **{s: [1.0] * 6 for s in SAMPLES}})
    meta = pd.DataFrame({"sample": SAMPLES, "condition": ["A", "A", "B", "B"]})
    monkeypatch.setattr(plot_images, "log2_qc_frame", lambda kind: frame)
    monkeypatch.setattr(plot_images, "_get_sample_columns", lambda kind, df: SAMPLES)
    monkeypatch.setattr(plot_images, "_metadata_for_kind", lambda kind, df, cols: meta.copy())
    monkeypatch.setattr(plot_images, "advanced_condition_colors", lambda kind, plt, conditions, advanced: {c: "#1f77b4" for c in conditions})
    figures = []
    monkeypatch.setattr(plot_images, "_to_png_bytes", lambda fig, plt, **kw: figures.append(fig) or b"")
    plot_images.qc_coverage_plot(kind="protein")
    assert figures[-1].axes[0].get_xlabel() == "Sample"
    plot_images.qc_coverage_plot(kind="protein", summary=True)
    assert figures[-1].axes[0].get_xlabel() == "Condition"


def test_percent_axes_state_the_unit_once():
    """'Percentage … (%)' said the unit twice; the label names the quantity, the unit is (%)."""
    for path in (
        ROOT / "backend" / "app" / "services" / "peptide_tools.py",
        ROOT / "backend" / "app" / "services" / "phospho_tools.py",
        ROOT / "proteomicscopylot" / "notebook_functions.py",
        ROOT / "proteomicscopylot" / "notebook_functions.R",
    ):
        text = path.read_text(encoding="utf-8")
        assert "Percentage of peptides with missed cleavage (%)" not in text, path.name
        assert "Percentage (%)" not in text, path.name
    for path in (ROOT / "backend" / "app" / "services" / "peptide_tools.py", ROOT / "proteomicscopylot" / "notebook_functions.py", ROOT / "proteomicscopylot" / "notebook_functions.R"):
        assert "Peptides with missed cleavage (%)" in path.read_text(encoding="utf-8"), path.name
    for path in (ROOT / "backend" / "app" / "services" / "phospho_tools.py", ROOT / "proteomicscopylot" / "notebook_functions.py", ROOT / "proteomicscopylot" / "notebook_functions.R"):
        assert "Share of sites (%)" in path.read_text(encoding="utf-8"), path.name
