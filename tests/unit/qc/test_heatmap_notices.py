"""Notices travel with the actual rendered matrix, including report/cache output."""

import copy
from urllib.parse import unquote

import numpy as np
import pandas as pd
import pytest


from app.api.plot_responses import png_response
from app.schemas.stats import AnovaRequest
from app.services.clustering_tools import CompletenessReport
from app.services import single_protein_tools as single, stats_tools as stats
from app.services.plot_export import PlotBytes, to_png_bytes
from app.services.report_function import _png_to_html


@pytest.fixture
def data():
    frame = pd.DataFrame({
        "Protein_group": ["P"] * 4, "ProteinNames": ["P1", "P2", "P3", "P4"],
        "GeneNames": ["G1", "G2", "G3", "G4"],
        "PTM_Collapse_key": [f"P~S{i}_M1" for i in range(4)],
        "A1": [1., 2., 3., np.nan], "A2": [2., 4., np.nan, np.nan],
        "adj_pval": [.001] * 4,
    })
    meta = pd.DataFrame({"sample": ["A1", "A2"], "condition": ["A", "A"]})
    return frame, meta


@pytest.mark.parametrize("cluster,used", [(False, 3), (True, 2)])
def test_single_protein_notice_matches_matrix_and_table(monkeypatch, data, cluster, used):
    frame, meta = data
    monkeypatch.setattr(single, "_analysis_frame", lambda *a, **k: (frame, None, meta))
    arguments = dict(kind="phospho", protein="P", conditions=["A"], include_id=False,
                     filter_m1=True, cluster_rows=cluster, cluster_cols=False, value_type="log2")
    matrix, _ = single._heatmap_matrix(**arguments)
    assert len(matrix) == used
    assert matrix.attrs["heatmap_notice"].startswith(f"Heatmap-usable phosphosites: {used} of 4")
    table = single.single_protein_heatmap_table(**arguments)
    assert list(table.PTM_Collapse_key) == list(matrix.index)
    image = single.single_protein_heatmap_plot(**arguments, dpi=72)
    assert image.notice == matrix.attrs["heatmap_notice"]


def test_anova_notice_counts_significant_input_and_actual_image(data):
    frame, meta = data
    frame.loc[3, "adj_pval"] = .8
    fig, plt = stats._anova_heatmap_figure(
        frame, meta, kind="protein", advanced=None, label_column="ProteinNames",
        p_value_threshold=.05, clustered=False, show_dendrograms=False, show_legend=False,
    )
    assert fig._copylot_notice.startswith("Heatmap-usable features: 2 of 3 (66.7%)")
    assert any(image.get_array().shape == (2, 2) for ax in fig.axes for image in ax.images)
    notice = fig._copylot_notice
    plt.close(fig)
    fig, ax = plt.subplots()
    ax.plot([1, 2])
    fig._copylot_notice = notice
    payload = to_png_bytes(fig, plt, dpi=72)
    assert unquote(png_response(payload).headers["X-CoPYlot-Notice"]) == payload.notice
    assert payload.notice in _png_to_html(payload)
    assert copy.deepcopy(payload).notice == payload.notice


@pytest.mark.parametrize("cluster,used", [(False, 3), (True, 2)])
def test_pathway_notice_counts_genes_not_source_rows(monkeypatch, data, cluster, used):
    frame, meta = data
    monkeypatch.setattr(stats, "_stats_source", lambda *a, **k: ("data", frame, meta, []))
    monkeypatch.setattr(stats, "load_go_db", lambda: pd.DataFrame({"description": ["test"], "genes": ["G1;G2;G3;G4"]}))
    # Capture the renderer's exact figure before serialization to avoid font-dependent layout.
    captured = {}
    def capture(fig, plt, **kwargs):
        captured["rows"] = fig.axes[0].images[0].get_array().shape[0]
        result = PlotBytes(b"png", fig._copylot_notice)
        plt.close(fig)
        return result
    monkeypatch.setattr(stats, "_fit_figure_to_labels", lambda *a, **k: None)
    monkeypatch.setattr(stats, "_to_png_bytes", capture)
    image = stats.pathway_heatmap_png(kind="protein", pathway="test", conditions=["A"],
                                    value_type="log2", remove_empty=True, cluster_rows=cluster, cluster_cols=False,
                                    include_id=False, header=True, width_cm=20, height_cm=12, dpi=72)
    assert captured["rows"] == used
    assert image.notice.startswith(f"Heatmap-usable genes: {used} of 4")


def test_notice_is_escaped_in_report_and_absent_from_plain_images():
    payload = PlotBytes(b"png", "<unsafe> & text")
    assert "&lt;unsafe&gt; &amp; text" in _png_to_html(payload)
    assert "X-CoPYlot-Notice" not in png_response(b"png").headers


@pytest.mark.parametrize("selected", [None, 1])
def test_cluster_heatmap_keeps_upstream_exclusion_counts(monkeypatch, data, selected):
    frame, meta = data
    kept = frame.iloc[:2].assign(cluster=[1, 2])
    report = CompletenessReport(kept=np.array([True, True, False, False]), dropped=2, total=4)
    monkeypatch.setattr(stats, "_anova_dataframe", lambda p: ("data", "ProteinNames", frame, []))
    monkeypatch.setattr(stats, "_stats_source", lambda *a, **k: ("data", frame, meta, []))
    monkeypatch.setattr(stats, "_anova_cluster_dataframe", lambda *a: (kept.copy(), report))
    result, metadata, label = stats._prepare_anova_plot_frame(AnovaRequest(kind="protein", source="anova_cluster"), selected)
    fig, plt = stats._anova_heatmap_figure(
        result, metadata, kind="protein", advanced=None, label_column=label,
        p_value_threshold=.05, clustered=True, show_dendrograms=False, show_legend=False,
        selected_cluster=selected,
    )
    try:
        if selected is None:
            assert fig._copylot_notice.startswith("Heatmap-usable features: 2 of 4 (50.0%)")
        else:
            assert fig._copylot_notice.startswith("Heatmap-usable features: 1 of 1 (100.0%)")
            assert "Before cluster selection, 2 of 4" in fig._copylot_notice
    finally:
        plt.close(fig)


@pytest.mark.parametrize("custom", [None, "My custom pathway title"])
def test_pathway_title_is_wrapped_to_the_heatmap_not_the_figure(monkeypatch, data, custom):
    # 2026-10-09: the title is re-wrapped to the axes width after layout, so it
    # no longer overhangs the gene labels to the figure's left edge.
    frame, meta = data
    monkeypatch.setattr(stats, "_stats_source", lambda *a, **k: ("data", frame, meta, []))
    long_name = "positive regulation of transcription by RNA polymerase II in response to a very long stimulus"
    monkeypatch.setattr(stats, "load_go_db", lambda: pd.DataFrame({"description": [long_name], "genes": ["G1;G2;G3;G4"]}))
    captured = {}

    def capture(fig, plt, **kwargs):
        ax = fig.axes[0]
        captured["lines"] = ax.get_title().count("\n") + 1
        captured["title"] = ax.get_title()
        captured["axes_cm"] = ax.get_position().width * fig.get_figwidth() * 2.54
        plt.close(fig)
        return PlotBytes(b"png", fig._copylot_notice)
    monkeypatch.setattr(stats, "_fit_figure_to_labels", lambda *a, **k: None)
    monkeypatch.setattr(stats, "_to_png_bytes", capture)
    stats.pathway_heatmap_png(kind="protein", pathway=long_name, conditions=["A"], value_type="log2",
                              remove_empty=True, cluster_rows=False, cluster_cols=False, include_id=False,
                              header=True, width_cm=20, height_cm=12, dpi=72,
                              advanced={"titleElement": {"text": custom}} if custom else None)
    figure_wrap = stats._wrapped_title(f"{long_name} (log2 Intensity; median across mapped features)", width_cm=20)
    assert captured["axes_cm"] < 20
    if custom:
        assert " ".join(captured["title"].split()) == custom
    else:
        assert captured["lines"] > figure_wrap.count("\n") + 1
