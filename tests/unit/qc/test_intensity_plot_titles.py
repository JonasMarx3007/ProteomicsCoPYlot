"""Titles say what the values are: condition means, not measured values.

The intensity histogram and the boxplot's Mean mode average each feature over
a condition's replicates before drawing; "measured intensity" was the title of
both, the same words Single mode uses for one sample's actual values.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from app.services import plot_images  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
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


# --- the same words in the two shipped packages ------------------------------------
#
# The packages are called on a small project; the pip package's matplotlib
# figures are read back, and the R package runs with its base-graphics calls
# wrapped so the `main`, `xlab` and `ylab` they are given, and every `mtext`,
# are recorded.

HISTOGRAM_TITLE = "Distribution of mean intensity per condition (log2)"
MEAN_BOXPLOT_TITLE = "Mean intensity per condition (log2)"
MISSED_CLEAVAGE_AXIS = "Peptides by missed cleavages (%)"
SITE_SHARE_AXIS = "Share of sites (%)"
ROW_LABELS = {"ProteinNames": "Proteins", "PTM_Collapse_key": "Phosphosites", "Phosphoprotein": "Phosphoproteins"}


def _package_frame(column: str = "ProteinNames") -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(4)
    frame = pd.DataFrame({column: [f"P{i}~S{i}_M1" if column == "PTM_Collapse_key" else f"P{i}" for i in range(6)],
                          **{s: rng.normal(20, 1, 6) for s in SAMPLES}})
    frame.loc[1, "A2"] = np.nan
    return frame, pd.DataFrame({"sample": SAMPLES, "condition": ["A", "A", "B", "B"]})


def _peptide_file(directory: Path) -> Path:
    path = directory / "peptides.tsv"
    pd.DataFrame([
        {"File.Name": sample, "Stripped.Sequence": sequence, "Modified.Sequence": sequence,
         "Precursor.Id": sequence + "2", "Precursor.Quantity": float(i + 1)}
        for sample in SAMPLES for i, sequence in enumerate(["AKR", "PEPTIDEK", "MPEPRK", "ARPK"])
    ]).to_csv(path, sep="\t", index=False)
    return path


STY_KEYS = ["PEP~GENE_S1_1", "PEP~GENE_T5_1", "PEP~GENE_Y9_1"]


def _pip_figures(tmp_path: Path) -> dict:
    from proteomicscopylot import notebook_functions as nb

    frame, meta = _package_frame()
    figures = {
        "histogram": nb.histo_int(frame, meta),
        "mean boxplot": nb.boxplot_int(frame, meta),
        "missed cleavages": nb.missed_cleavage_plot(str(_peptide_file(tmp_path)), meta),
        "sty": nb.sty_plot(pd.DataFrame({"PTM_Collapse_key": STY_KEYS})),
    }
    for column in ROW_LABELS:
        figures[f"heatmap {column}"] = nb.missing_value_heatmap(*_package_frame(column))
    return figures


def _labels(fig) -> set[str]:
    """Titles and axis labels, including a secondary axis (a child of its parent)."""
    axes = [*fig.axes, *(child for axis in fig.axes for child in axis.child_axes)]
    texts = {axis.get_title() for axis in fig.axes}
    texts |= {label for axis in axes for label in (axis.xaxis.get_label_text(), axis.yaxis.get_label_text())}
    return {text for text in texts if text}


R_LABEL_SCRIPT = """
suppressMessages(source("proteomicscopylot/notebook_functions.R"))
args <- commandArgs(TRUE)
records <- list()
current <- ""
note <- function(...) records[[current]] <<- unique(c(records[[current]], unlist(list(...))))
for (name in c("plot", "boxplot", "barplot", "image", "hist")) local({
  original <- get(name, envir = asNamespace("graphics"))
  assign(name, function(...) {
    given <- list(...)
    note(given$main, given$xlab, given$ylab)
    original(...)
  }, envir = globalenv())
})
mtext <- function(text, ...) { note(text); graphics::mtext(text, ...) }
grDevices::pdf(NULL)
run <- function(label, expr) { current <<- label; records[[label]] <<- character(0); force(expr) }
meta <- data.frame(sample = c("A1", "A2", "B1", "B2"), condition = c("A", "A", "B", "B"))
protein <- read.csv(args[1], check.names = FALSE)
run("histogram", histo_int(protein, meta))
run("mean boxplot", boxplot_int(protein, meta))
run("missed cleavages", missed_cleavage_plot(args[2], meta))
run("sty", sty_plot(data.frame(PTM_Collapse_key = c("PEP~GENE_S1_1", "PEP~GENE_T5_1", "PEP~GENE_Y9_1"))))
for (i in 3:5) {
  frame <- read.csv(args[i], check.names = FALSE)
  run(paste("heatmap", names(frame)[1]), missing_value_heatmap(frame, meta))
}
invisible(grDevices::dev.off())
cat(jsonlite::toJSON(lapply(records, I)))
"""


def _r_labels(rscript: str, tmp_path: Path) -> dict[str, set[str]]:
    import json
    import subprocess

    paths = []
    for name, column in (("protein", "ProteinNames"), *((column, column) for column in ROW_LABELS)):
        path = tmp_path / f"{name}.csv"
        _package_frame(column)[0].to_csv(path, index=False)
        paths.append(path)
    arguments = [str(paths[0]), str(_peptide_file(tmp_path)), *(str(path) for path in paths[1:])]
    result = subprocess.run([rscript, "-e", R_LABEL_SCRIPT, *arguments], cwd=ROOT,
                            capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    return {label: set(texts) for label, texts in json.loads(result.stdout).items()}


def test_the_pip_package_uses_the_app_s_titles(tmp_path) -> None:
    figures = _pip_figures(tmp_path)
    assert figures["histogram"].axes[0].get_title() == HISTOGRAM_TITLE
    assert figures["mean boxplot"].axes[0].get_title() == MEAN_BOXPLOT_TITLE
    for fig in figures.values():
        assert not any("measured intensity (log2)" in text.lower() for text in _labels(fig))


@pytest.mark.requires_r("jsonlite")
def test_the_three_pipelines_use_the_same_titles(rscript, tmp_path) -> None:
    labels = _r_labels(rscript, tmp_path)
    assert HISTOGRAM_TITLE in labels["histogram"], labels["histogram"]
    assert MEAN_BOXPLOT_TITLE in labels["mean boxplot"], labels["mean boxplot"]
    for texts in labels.values():
        assert not any("measured intensity (log2)" in text.lower() for text in texts)


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


@pytest.mark.parametrize("column,label", list(ROW_LABELS.items()))
def test_the_pip_heatmap_names_its_rows_by_level(column: str, label: str) -> None:
    from proteomicscopylot import notebook_functions as nb

    fig = nb.missing_value_heatmap(*_package_frame(column))
    assert fig.axes[0].get_ylabel() == label


@pytest.mark.requires_r("jsonlite")
def test_pip_and_r_heatmaps_name_their_rows_by_level(rscript, tmp_path) -> None:
    labels = _r_labels(rscript, tmp_path)
    for column, label in ROW_LABELS.items():
        texts = labels[f"heatmap {column}"]
        assert label in texts, (column, texts)
        assert "Protein Numbers" not in texts


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


def _assert_unit_stated_once(texts: set[str], where: str) -> None:
    for text in texts:
        assert "Percentage" not in text or "(%)" not in text, f"{where}: {text!r} says the unit twice"
        assert text != "Peptides with missed cleavage (%)", f"{where}: the bars include the 0-missed class"


def test_percent_axes_state_the_unit_once_in_the_app(example_project, monkeypatch, tmp_path) -> None:
    """'Percentage ... (%)' said the unit twice; the label names the quantity, the unit is (%).

    The bars include the 0-missed class and sum to 100 %, so the axis is the
    share of peptides by number of missed cleavages, not "with" one (2026-10-02).
    """
    from app.services import peptide_tools, phospho_tools
    from app.services.annotation_store import get_annotation
    from app.services.dataset_store import save_peptide_path
    from app.services.peptide_metadata_store import save_peptide_metadata
    from app.services.runtime_cache import invalidate_runtime_cache

    figures = []
    for module in (peptide_tools, phospho_tools):
        monkeypatch.setattr(module, "_to_png_bytes", lambda fig, plt, **kw: figures.append(fig) or b"")
    metadata = get_annotation("protein").metadata.copy()
    peptides = tmp_path / "peptides.tsv"
    pd.DataFrame([
        {"File.Name": sample, "Stripped.Sequence": sequence, "Modified.Sequence": sequence,
         "Precursor.Id": sequence + "2", "Precursor.Quantity": float(i + 1)}
        for sample in metadata["sample"] for i, sequence in enumerate(["AKR", "PEPTIDEK", "MPEPRK"])
    ]).to_csv(peptides, sep="\t", index=False)
    save_peptide_path(str(peptides))
    save_peptide_metadata("metadata.csv", metadata)
    monkeypatch.setattr(
        phospho_tools, "_phospho_context",
        lambda: (pd.DataFrame({"PTM_Collapse_key": STY_KEYS}), pd.DataFrame(), []),
    )
    invalidate_runtime_cache("test")

    peptide_tools.peptide_missed_cleavage_plot()
    missed = _labels(figures[-1])
    phospho_tools.phospho_sty_png()
    sty = _labels(figures[-1])

    assert MISSED_CLEAVAGE_AXIS in missed, missed
    assert SITE_SHARE_AXIS in sty, sty
    _assert_unit_stated_once(missed | sty, "app")


def test_percent_axes_state_the_unit_once_in_the_pip_package(tmp_path) -> None:
    figures = _pip_figures(tmp_path)
    missed, sty = _labels(figures["missed cleavages"]), _labels(figures["sty"])
    assert MISSED_CLEAVAGE_AXIS in missed, missed
    assert SITE_SHARE_AXIS in sty, sty
    _assert_unit_stated_once(missed | sty, "pip package")


@pytest.mark.requires_r("jsonlite")
def test_percent_axes_state_the_unit_once_in_the_r_package(rscript, tmp_path) -> None:
    labels = _r_labels(rscript, tmp_path)
    assert MISSED_CLEAVAGE_AXIS in labels["missed cleavages"], labels["missed cleavages"]
    assert SITE_SHARE_AXIS in labels["sty"], labels["sty"]
    _assert_unit_stated_once(labels["missed cleavages"] | labels["sty"], "R package")
