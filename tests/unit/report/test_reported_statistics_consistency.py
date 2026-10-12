from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]

import app.services.completeness_tools as ct


@pytest.mark.parametrize("kind,workflow,key", [
    ("protein","Protein","ProteinNames"),
    ("phospho","Phosphosite","PTM_Collapse_key"),
    ("phosprot","Phosphoprotein","Phosphoprotein"),
])
@pytest.mark.parametrize("scale", ["linear", "log2"])
@pytest.mark.parametrize("centered", [False, True])
def test_abundance_ranks_each_condition_independently(monkeypatch,kind,workflow,key,scale,centered):
    from app.services import plot_images as plots, ai_functions
    from proteomicscopylot import notebook_functions as nb
    import matplotlib.pyplot as plt
    frame = pd.DataFrame({key:["A_only","B_only","shared","absent","partial"],
        "a1":[100.,np.nan,10.,np.nan,1.], "a2":[120.,np.nan,12.,np.nan,np.nan],
        "b1":[np.nan,200.,30.,np.nan,np.nan], "b2":[np.nan,220.,32.,np.nan,np.nan],
        "c1":[np.nan]*5, "c2":[np.nan]*5})
    if kind == "phosprot":
        frame["site_num"] = 1
        frame["PTM_Collapse_keys"] = "site"
    samples = ["a1","a2","b1","b2","c1","c2"]
    meta = pd.DataFrame({"sample":samples,"condition":["A","A","B","B","C","C"]})
    original = frame.copy(deep=True)
    monkeypatch.setattr(plots,"linear_qc_frame",lambda kind: frame.copy())
    monkeypatch.setattr(plots,"_get_sample_columns",lambda kind,data:samples)
    monkeypatch.setattr(plots,"_metadata_for_kind",lambda *args:meta.copy())
    monkeypatch.setattr(plots,"phosprot_values_are_centred",lambda kind:False)
    monkeypatch.setattr(plots,"_plotly_html",lambda fig:fig)
    # log10 of the mean, with no pseudocount. The third A value is the reason:
    # a feature whose mean is exactly 1.0 belongs at 0.0 on a log10 axis, and
    # `log10(x + 1)` put it at 0.301 -- a tenfold-looking offset on the part of
    # the curve the plot exists to show.
    expected = {"A":np.log10(np.array([110.,11.,1.])),
                "B":np.log10(np.array([210.,31.])), "C":np.array([])}
    ranked, _, _ = plots._abundance_rank_frame(kind)
    assert set(zip(ranked.Feature,ranked.Condition)) == {
        ("A_only","A"),("partial","A"),("shared","A"),("B_only","B"),("shared","B")}
    for condition, values in expected.items():
        rows = ranked[ranked.Condition == condition].sort_values("Rank")
        np.testing.assert_allclose(rows.log10Intensity,values)
        np.testing.assert_array_equal(rows.Rank,np.arange(1,len(values)+1))
    def check_scatter(ax, conditions):
        for collection, condition in zip(ax.collections, conditions):
            points = np.asarray(collection.get_offsets())
            points = points[np.argsort(points[:,0])]
            np.testing.assert_allclose(points[:,1],expected[condition])
            np.testing.assert_array_equal(points[:,0],np.arange(1,len(points)+1))
    def capture(fig,*args,**kwargs):
        try:
            check_scatter(fig.axes[0],visible)
        finally:
            plt.close(fig)
        return b"checked"
    monkeypatch.setattr(plots,"_to_png_bytes",capture)
    for selection, visible in [("All Conditions",["A","B","C"]),("A",["A"]),("B",["B"]),("C",["C"])]:
        assert plots.qc_abundance_plot(kind,condition=selection,legend=False) == b"checked"
        # The renderer itself, not the copy the result cache hands out: copying a
        # plotly figure re-encodes its arrays into plotly's binary form, which is
        # equivalent in the HTML the route serves but is not a sequence to read here.
        fig = plots.qc_abundance_interactive_html.__wrapped__(kind,condition=selection)
        for trace in fig.data:
            np.testing.assert_allclose(sorted(trace.y,reverse=True),expected[trace.name])
        assert sum(len(trace.y) for trace in fig.data) == sum(len(expected[c]) for c in visible)
    notebook_input = frame.copy()
    if scale == "log2":
        notebook_input[samples] = np.log2(notebook_input[samples])
    before = notebook_input.copy(deep=True)
    fig = nb.abundance_plot(notebook_input,meta,workflow=workflow,data_scale=scale,centered=centered,legend=False)
    try:
        check_scatter(fig.axes[0],["A","B","C"])
        assert fig.axes[0].get_ylabel() == nb.abundance_axis_label(workflow,centered)
    finally:
        plt.close(fig)
    for condition in expected:
        fig = nb.interactive_abundance_plot(notebook_input,meta,condition,workflow=workflow,data_scale=scale,centered=centered)
        assert fig.layout.yaxis.title.text == nb.abundance_axis_label(workflow,centered)
        values = [y for trace in fig.data for y in trace.y]
        np.testing.assert_allclose(sorted(values,reverse=True),expected[condition])
    monkeypatch.setattr(ai_functions,"phosprot_values_are_centred",lambda kind:centered)
    lines = ai_functions._abundance_data_lines(workflow,limit=10)
    assert any("condition=A|rank=1|identifier=A_only|" in line for line in lines)
    # The assistant names the measure it reports as the plot draws it: log10 of
    # the mean, with no pseudocount (it once said "plus 1" of centred values).
    header = next(line for line in lines if line.startswith("abundance_data|"))
    assert header.endswith("value=" + ("log10_of_mean_ratio_to_site_median" if centered
                                       else "log10_of_mean_linear_intensity")), header
    top = next(line for line in lines if "condition=A|rank=1|" in line)
    assert float(top.rsplit("=", 1)[1]) == pytest.approx(max(expected["A"]), abs=1e-4)
    assert not any("condition=B|" in line and "identifier=A_only|" in line for line in lines)
    pd.testing.assert_frame_equal(frame,original)
    pd.testing.assert_frame_equal(notebook_input,before)


@pytest.mark.requires_r("plotly")
def test_r_abundance_membership_matches_each_condition():
    import subprocess
    from app.services.r_runtime import detect_r_runtime
    runtime = detect_r_runtime()
    script = r'''
      source("proteomicscopylot/notebook_functions.R")
      d <- data.frame(ProteinNames=c("A_only","B_only","shared","absent","partial"),
        a1=c(100,NA,10,NA,1),a2=c(120,NA,12,NA,NA),
        b1=c(NA,200,30,NA,NA),b2=c(NA,220,32,NA,NA),c1=NA_real_,c2=NA_real_)
      m <- data.frame(sample=names(d)[-1],condition=rep(c("A","B","C"),each=2))
      expected <- list(log10(c(110,11,1)),log10(c(210,31)),numeric())
      grDevices::pdf(NULL)
      trace("points.default",where=asNamespace("graphics"),print=FALSE,
        tracer=quote({
          stopifnot(isTRUE(all.equal(as.numeric(y),expected[[plot_index]])))
          plot_index <<- plot_index + 1L
        }))
      for (workflow in c("Protein","Phosphosite","Phosphoprotein")) {
       for (scale in c("linear","log2")) for (centered in c(FALSE,TRUE)) {
        input <- d
        names(input)[1] <- .workflow_col(workflow)
        input$site_num <- 1
        input$PTM_Collapse_keys <- "site"
        if (scale == "log2") input[m$sample] <- log2(input[m$sample])
        before <- input
        plot_index <- 1L
        abundance_plot(input,m,workflow=workflow,data_scale=scale,centered=centered,legend=FALSE)
        stopifnot(plot_index == 4L)
        plot_index <- 3L
        abundance_plot(input,m[m$condition == "C",],workflow=workflow,data_scale=scale,centered=centered,legend=FALSE)
        stopifnot(plot_index == 4L)
        for (i in seq_along(expected)) {
          fig <- interactive_abundance_plot(input,m,c("A","B","C")[i],workflow=workflow,data_scale=scale,centered=centered)
          stopifnot(fig$x$layoutAttrs[[1]]$yaxis$title == abundance_axis_label(workflow,centered))
          traces <- plotly::plotly_build(fig)$x$data
          values <- unlist(lapply(traces,function(trace) trace$y))
          stopifnot(isTRUE(all.equal(sort(as.numeric(values),decreasing=TRUE),expected[[i]])))
        }
        stopifnot(identical(input,before))
       }
      }
      untrace("points.default",where=asNamespace("graphics"))
      grDevices::dev.off()
    '''
    result = subprocess.run([runtime["executable"],"-e",script],cwd=ROOT,
                            capture_output=True,text=True,timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('method', ['Matrix', 'Ellipse'])
@pytest.mark.parametrize('full_range', [False, True])
@pytest.mark.parametrize('values', [
    {'a': [1, 1, 1], 'b': [1, 2, 3]},
    {'a': [1, 1, 1], 'b': [2, 2, 2]},
    {'a': [1, 2, None], 'b': [None, 3, 4]},
    {'a': [1, 2, 3], 'b': [1, 0, 1]},
])
def test_correlation_plots_preserve_undefined_values(monkeypatch, method, full_range, values):
    from app.services import plot_images, ai_functions
    from proteomicscopylot import notebook_functions as nb
    import scipy.cluster.hierarchy as hierarchy
    import matplotlib.pyplot as plt
    frame = pd.DataFrame(values)
    meta = pd.DataFrame({'sample': ['a', 'b'], 'condition': ['C', 'C']})
    expected = frame.corr().to_numpy()
    incomplete = not np.isfinite(expected).all()
    if incomplete:
        def no_clustering(*args, **kwargs):
            pytest.fail('Undefined correlations must not be converted into clustering distances')
        monkeypatch.setattr(hierarchy, 'linkage', no_clustering)
        monkeypatch.setattr(nb, 'linkage', no_clustering)
    monkeypatch.setattr(plot_images, 'log2_qc_frame', lambda _: frame)
    monkeypatch.setattr(plot_images, '_get_sample_columns', lambda *a: ['a', 'b'])
    monkeypatch.setattr(plot_images, '_metadata_for_kind', lambda *a: meta)
    def check(fig):
        ax = fig.axes[0]
        assert sum(text.get_text() == 'NA' for text in ax.texts) == np.isnan(expected).sum()
        assert ('clustering skipped' in ax.get_xlabel()) == incomplete
        if incomplete:
            assert [label.get_text() for label in ax.get_xticklabels()] == ['C_1', 'C_2']
        if method == 'Matrix':
            # One rectangle per cell (vector in SVG/PDF), in matrix order.
            from matplotlib.collections import QuadMesh
            mesh = next(child for child in ax.collections if isinstance(child, QuadMesh))
            actual = np.ma.asarray(mesh.get_array()).reshape(expected.shape)
            np.testing.assert_array_equal(np.ma.getmaskarray(actual), np.isnan(expected))
            np.testing.assert_allclose(actual.filled(np.nan), expected, equal_nan=True)
            assert np.isfinite(mesh.get_clim()).all()
        else:
            assert len(ax.patches) == np.isfinite(expected).sum()
    def capture(fig, plt, **kwargs):
        try:
            check(fig)
        finally:
            plt.close(fig)
        return b'png'
    monkeypatch.setattr(plot_images, '_to_png_bytes', capture)
    assert plot_images.qc_correlation_plot('protein', method=method, full_range=full_range) == b'png'
    fig = nb.corr_plot(frame, meta, method=method, id=False, full_range=full_range)
    try:
        check(fig)
    finally:
        plt.close(fig)
    if np.isnan(expected[0, 1]):
        assert 'no_finite_pairs' in '\n'.join(ai_functions._correlation_data_lines('protein'))


@pytest.mark.parametrize("log2", [False, True])
def test_phospho_coverage_scale_and_unknowns(monkeypatch, log2):
    from types import SimpleNamespace
    from app.services import phospho_tools as p
    from app.services.runtime_cache import invalidate_runtime_cache
    frame = pd.DataFrame({"PTM_localization": [.99, .5, np.nan, .9],
                          "s1": [10., 0., 20., np.inf], "s2": [10., 5., 20., np.nan]})
    meta = pd.DataFrame({"sample": ["s1", "s2"], "condition": ["A", "A"]})
    monkeypatch.setattr(p, "_phospho_context", lambda: (frame, meta, ["s1", "s2"]))
    monkeypatch.setattr(p, "get_annotation", lambda kind: SimpleNamespace(is_log2_transformed=log2))
    invalidate_runtime_cache("test")
    try:
        counts, summary = p._coverage_counts()
        from proteomicscopylot import notebook_functions as nb
        notebook_counts = nb._phossite_coverage_counts(frame, meta, is_log2=log2)
        np.testing.assert_array_equal(notebook_counts.to_numpy(), counts[["Class I", "Not Class I", "Unclassified"]].to_numpy())
        import matplotlib.pyplot as plt
        for plot in (nb.phossite_coverage_plot, nb.phossite_coverage_plot_summary):
            fig = plot(frame, meta, is_log2=log2, dpi=72)
            assert len(fig.axes[0].patches) == (6 if plot is nb.phossite_coverage_plot else 3)
            plt.close(fig)
        assert counts["Class I"].tolist() == [1, 1]
        assert counts["Not Class I"].tolist() == [int(log2), 1]
        assert counts["Unclassified"].tolist() == [1, 1]
        assert counts["Total"].tolist() == [2 + int(log2), 3]
        assert summary["totalMean"].iloc[0] == (5 + int(log2)) / 2
        def check(fig, plt, **kwargs):
            try:
                bars = np.array([bar.get_height() for bar in fig.axes[0].patches]).reshape(3, 2)
                assert bars.sum(axis=0).tolist() == counts["Total"].tolist()
            finally:
                plt.close(fig)
            return b"verified"
        monkeypatch.setattr(p, "_to_png_bytes", check)
        assert p.phospho_coverage_png() == b"verified"
    finally:
        invalidate_runtime_cache("test")


@pytest.mark.parametrize("keys,expected", [
    (["P~GENE_S1_1", "P_T2"], [1, 1, 0]),
    (["P_T2"], [0, 1, 0]),
    (["P~GENE_S1_1", "junk", None, "PROTEINS12"], [1, 0, 0, 3]),
    (["junk"], [0, 0, 0, 1]), ([], [0, 0, 0]),
])
def test_sty_formats_and_unknowns(monkeypatch, keys, expected):
    import matplotlib.pyplot as plt
    from app.services import phospho_tools as p
    from proteomicscopylot import notebook_functions as nb
    from app.services.runtime_cache import invalidate_runtime_cache
    frame = pd.DataFrame({"PTM_Collapse_key": keys})
    monkeypatch.setattr(p, "_phospho_context", lambda: (frame, pd.DataFrame(), []))
    invalidate_runtime_cache("test")
    try:
        result = p.phospho_sty_table()
        assert result["Count"].tolist() == expected
        assert result["Count"].sum() == len(keys)
        if keys:
            assert result["Percentage"].sum() == pytest.approx(100, abs=.02)
        def check():
            fig = plt.gcf()
            try:
                assert [bar.get_height() for bar in fig.axes[0].patches] == expected
            finally:
                plt.close(fig)
        monkeypatch.setattr(plt, "show", check)
        nb.sty_plot(frame)
    finally:
        invalidate_runtime_cache("test")


@pytest.mark.parametrize("values", [[0, 1, 2, 3, 10], [1, 1, 1, 1, 10], [2, 2, 2], [1], [1, 2]])
@pytest.mark.parametrize("mode", ["mean", "single", "cv"])
def test_exported_whiskers_match_rendered_endpoints(values, mode):
    import matplotlib.pyplot as plt
    from app.services import table_functions as tables

    values = np.asarray(values, dtype=float)
    meta = pd.DataFrame({"sample": ["a", "b"], "condition": ["A", "A"]})
    if mode == "cv":
        delta = values / (10 * np.sqrt(2))
        frame = pd.DataFrame({"a": 10 - delta, "b": 10 + delta})
        plotted = frame.std(axis=1) / frame.mean(axis=1) * 100
        result = tables.prepare_cov_df(frame, meta)
    else:
        frame = pd.DataFrame({"a": values, "b": values})
        plotted = values
        result = (tables.prepare_boxplot_df if mode == "mean" else tables.prepare_boxplot_single_df)(frame, meta)
    fig, ax = plt.subplots()
    try:
        artists = ax.boxplot(plotted, whis=1.5)
        assert result.iloc[0]["lower_whisker"] == round(float(artists["whiskers"][0].get_ydata()[-1]), 2)
        assert result.iloc[0]["upper_whisker"] == round(float(artists["whiskers"][1].get_ydata()[-1]), 2)
    finally:
        plt.close(fig)


@pytest.mark.parametrize("implementation", ["backend", "notebook"])
@pytest.mark.parametrize("counts", [[6, 3, 1], [0, 0, 0]])
def test_sty_percentage_axis_tracks_counts(monkeypatch, implementation, counts):
    import matplotlib.pyplot as plt
    from app.services import phospho_tools
    from app.services.runtime_cache import invalidate_runtime_cache
    from proteomicscopylot import notebook_functions as nb

    def check(fig):
        try:
            ax = fig.axes[0]
            ax.set_ylim(0, 20)
            fig.canvas.draw()
            if sum(counts):
                secondary = ax.child_axes[0]
                assert secondary.get_ylim() == pytest.approx((0, 200))
                assert ax.transData.transform((0, 6))[1] == pytest.approx(secondary.transData.transform((0, 60))[1])
            else:
                assert not ax.child_axes
        finally:
            plt.close(fig)
        return b"verified"

    invalidate_runtime_cache("test")
    try:
        if implementation == "backend":
            table = pd.DataFrame({"Residue": ["S", "T", "Y"], "Count": counts,
                                  "Percentage": np.asarray(counts) * 10})
            monkeypatch.setattr(phospho_tools, "phospho_sty_table", lambda: table)
            monkeypatch.setattr(phospho_tools, "_to_png_bytes", lambda fig, *args, **kwargs: check(fig))
            assert phospho_tools.phospho_sty_png() == b"verified"
        else:
            keys = [f"P~x_{residue}1_x" for residue, count in zip("STY", counts) for _ in range(count)]
            monkeypatch.setattr(plt, "show", lambda: check(plt.gcf()))
            nb.sty_plot(pd.DataFrame({"PTM_Collapse_key": keys}))
    finally:
        invalidate_runtime_cache("test")


@pytest.mark.parametrize("aggregation", ["robust_site_median", "mean"])
@pytest.mark.parametrize("value_type", ["z", "log2"])
def test_pathway_heatmap_units_follow_provenance(monkeypatch, aggregation, value_type):
    from types import SimpleNamespace
    from app.services import stats_tools, annotation_store
    from app.services.runtime_cache import invalidate_runtime_cache

    frame = pd.DataFrame({"GeneNames": ["G"], "a": [-1.5], "b": [1.5]})
    meta = pd.DataFrame({"sample": ["a", "b"], "condition": ["A", "B"]})
    monkeypatch.setattr(stats_tools, "_stats_source", lambda *a, **k: ("filtered", frame, meta, []))
    monkeypatch.setattr(stats_tools, "load_go_db", lambda organism="human": pd.DataFrame({"description": ["path"], "genes": ["G"]}))
    monkeypatch.setattr(annotation_store, "get_annotation", lambda kind: SimpleNamespace(phosprot_aggregation=aggregation))
    expected = "Z-score" if value_type == "z" else (
        "log2 Ratio to Site Median" if aggregation == "robust_site_median" else "log2 Intensity"
    )
    def check(fig, plt, **kwargs):
        try:
            assert fig.axes[1].get_ylabel() == expected
            assert ("Z-transformed" if value_type == "z" else expected) in fig.axes[0].get_title()
        finally:
            plt.close(fig)
        return b"verified"
    monkeypatch.setattr(stats_tools, "_to_png_bytes", check)
    invalidate_runtime_cache("test")
    try:
        assert stats_tools.pathway_heatmap_png(
            kind="phosprot", pathway="path", conditions=[], value_type=value_type,
            include_id=False, header=True, remove_empty=True, cluster_rows=False,
            cluster_cols=False, width_cm=12, height_cm=8, dpi=72,
        ) == b"verified"
    finally:
        invalidate_runtime_cache("test")


def test_ai_context_uses_the_same_ddof_as_the_statistical_paths(monkeypatch) -> None:
    """The assistant quotes the spread of the condition means it was shown.

    Condition A's feature means are 1, 2, 3 and 4: their sample SD is 1.29, the
    population SD 1.12 (for B's 2, 2, 2, 6: 2 against 1.73). The context has to say the former, the number every
    statistical path and the result tables use.
    """
    from app.services import ai_functions

    frame = pd.DataFrame({"a1": [1.0, 2.0, 3.0, 4.0], "a2": [1.0, 2.0, 3.0, 4.0],
                          "b1": [2.0, 2.0, 2.0, 6.0], "b2": [2.0, 2.0, 2.0, 6.0]})
    meta = pd.DataFrame({"sample": list(frame.columns), "condition": ["A", "A", "B", "B"]})
    monkeypatch.setattr(ai_functions._plot_images, "log2_qc_frame", lambda kind: frame)
    monkeypatch.setattr(ai_functions._plot_images, "_get_sample_columns", lambda kind, data: list(frame.columns))
    monkeypatch.setattr(ai_functions._plot_images, "_metadata_for_kind", lambda kind, data, columns: meta.copy())

    lines = ai_functions._histogram_data_lines("protein")
    stats = {line.split("condition=")[1].split("|")[0]: line for line in lines
             if line.startswith("histogram_condition_stats|")}
    fmt = ai_functions._fmt_value
    assert f"|sd={fmt(np.std([1, 2, 3, 4], ddof=1))}|" in stats["A"], stats["A"]
    assert f"|sd={fmt(np.std([2, 2, 2, 6], ddof=1))}|" in stats["B"], stats["B"]
    summary = next(line for line in lines if line.startswith("histogram_answer_summary|"))
    expected = round(np.std([2, 2, 2, 6], ddof=1), 2) - round(np.std([1, 2, 3, 4], ddof=1), 2)
    assert f"sd_difference_right_minus_left={fmt(expected)}" in summary, summary


@pytest.mark.parametrize("n", [3, 4, 5])
def test_the_two_conventions_really_do_differ_at_these_group_sizes(n: int) -> None:
    values = pd.Series(np.random.default_rng(n).normal(20, 1.5, n))
    assert values.std(ddof=0) < values.std(ddof=1)
    understatement = 1 - values.std(ddof=0) / values.std(ddof=1)
    assert understatement > 0.10, "expected a double-digit gap at proteomics n"


def test_pandas_default_matches_the_statistical_convention() -> None:
    values = pd.Series([1.0, 2.0, 4.0])
    assert values.std() == values.std(ddof=1)


def _peptide_frame(runs: list[str]) -> pd.DataFrame:
    rng = np.random.default_rng(3)
    rows = []
    for run in runs:
        for index in range(40):
            precursor = f"PEP{index}_2"
            base = {
                "File.Name": run,
                "Precursor.Id": precursor,
                "Stripped.Sequence": precursor.split("_")[0],
            }
            quantities = (
                [0.0, float(rng.integers(100, 1000))]
                if index % 5 == 0
                else [float(rng.integers(100, 1000)), float(rng.integers(100, 1000))]
            )
            for quantity in quantities:
                rows.append({**base, "Precursor.Quantity": quantity})
    return pd.DataFrame(rows)


RUNS = [f"run_{i}.raw" for i in (1, 2, 3, 4)]


def _render(frame: pd.DataFrame, builder) -> bytes:
    class _Annotation:
        metadata = pd.DataFrame({"sample": RUNS, "condition": ["A"] * len(RUNS)})

    with patch("app.services.peptide_tools.get_annotation", return_value=_Annotation()), patch(
        "app.services.peptide_tools.get_current_dataset", return_value=object()
    ), patch(
        "app.services.peptide_tools.get_peptide_frame", return_value=frame
    ):
        return builder(dpi=50, width_cm=12, height_cm=8)


BUILDERS = {
    "precursor": ct.completeness_missing_value_plot_precursor,
    "peptide": ct.completeness_missing_value_plot_peptide,
}


@pytest.mark.parametrize("level,expected", [("peptide", [1, 2]), ("precursor", [2, 2])])
@pytest.mark.parametrize("runs,samples", [
    (["r1", "r2"], ["r1", "r2"]),
    (["ctrl_01.raw", "treat_01.raw"], ["ctrl_01.raw", "treat_01.raw"]),
    (["run_1.raw", "run_2.raw"], ["sample_1", "sample_2"]),
])
def test_peptide_coverage_counts_selected_entities_and_excludes_zeros(monkeypatch, level, expected, runs, samples):
    from app.services import plot_images, peptide_tools

    frame = pd.DataFrame({
        "File.Name": [runs[0]] * 3 + [runs[1]] * 3,
        "Stripped.Sequence": ["PEPA", "PEPA", "PEPB"] * 2,
        "Precursor.Id": ["PEPA_2", "PEPA_3", "PEPB_2"] * 2,
        "Precursor.Quantity": [10., 20., 0., 0., 30., 5.],
    })
    monkeypatch.setattr(peptide_tools, "get_peptide_frame", lambda: frame)
    metadata = pd.DataFrame({
        "sample": samples,
        "label": ["A", "B"], "condition": ["A", "B"],
    }).iloc[::-1]
    monkeypatch.setattr(plot_images, "_peptide_coverage_metadata", lambda *a, **k: metadata)

    def check_figure(fig, plt, **kwargs):
        try:
            assert [bar.get_height() for bar in fig.axes[0].patches] == expected[::-1]
            assert [tick.get_text() for tick in fig.axes[0].get_xticklabels()] == ["B", "A"]
            assert fig.axes[0].patches[0].get_facecolor() != fig.axes[0].patches[1].get_facecolor()
            assert fig.axes[0].get_ylabel() == f"Number of {level}s"
            assert fig.axes[0].get_title() == f"{level.capitalize()}s per sample"
        finally:
            plt.close(fig)
        return b"verified"

    monkeypatch.setattr(plot_images, "_to_png_bytes", check_figure)
    assert plot_images.qc_peptide_coverage_plot(level=level) == b"verified"

    def check_missing_matrix(matrix, **kwargs):
        assert matrix.notna().sum().tolist() == expected
        assert len(matrix) == (2 if level == "peptide" else 3)
        assert kwargs["title_label"] == level.capitalize()
        return b"verified"

    monkeypatch.setattr(ct, "_peptide_sample_columns", lambda frame: runs)
    monkeypatch.setattr(ct, "_missing_value_plot_from_matrix", check_missing_matrix)
    assert BUILDERS[level](dpi=72) == b"verified"


@pytest.mark.parametrize("level", ["peptide", "precursor"])
def test_peptide_coverage_rejects_ambiguous_numeric_fallback(monkeypatch, level):
    from app.services import plot_images, peptide_tools

    monkeypatch.setattr(peptide_tools, "get_peptide_frame", lambda: _peptide_frame(
        ["ctrl_01.raw", "treat_01.raw"]
    ))
    metadata = pd.DataFrame({
        "sample": ["sample_01"], "label": ["A_1"], "condition": ["A"],
    })
    monkeypatch.setattr(plot_images, "_peptide_coverage_metadata", lambda *a, **k: metadata)
    with pytest.raises(ValueError, match="ambiguous"):
        plot_images.qc_peptide_coverage_plot(level=level)


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_completeness_is_independent_of_input_row_order(name: str) -> None:
    frame = _peptide_frame(RUNS)
    reversed_rows = frame.iloc[::-1].reset_index(drop=True)
    assert _render(frame, BUILDERS[name]) == _render(reversed_rows, BUILDERS[name]), (
        f"{name} completeness changed when the input rows were reordered"
    )


@pytest.mark.parametrize("level", ["peptide", "precursor"])
def test_both_pivots_use_the_same_collapse_rule(monkeypatch, level: str) -> None:
    """Duplicate rows for one feature in one run collapse to their maximum, at both levels.

    One precursor is reported twice per run: once as 0 (not observed) and once
    with a value, and once with two different values. The matrix the
    completeness plots count from must hold the larger value in both cases --
    neither the zero (which would hide an observation), nor the mean or the sum
    (which would change the intensity), nor whichever row came first.
    """
    frame = pd.DataFrame({
        "File.Name": ["run_1.raw"] * 4 + ["run_2.raw"] * 4,
        "Precursor.Id": ["PEPA_2", "PEPA_2", "PEPB_2", "PEPB_2"] * 2,
        "Stripped.Sequence": ["PEPA", "PEPA", "PEPB", "PEPB"] * 2,
        "Precursor.Quantity": [0.0, 700.0, 300.0, 500.0, 900.0, 0.0, 800.0, 200.0],
    })
    monkeypatch.setattr(ct, "_peptide_sample_columns", lambda frame: ["run_1.raw", "run_2.raw"])
    with patch("app.services.peptide_tools.get_peptide_frame", return_value=frame):
        matrix = ct.completeness_peptide_matrix(level)
    features = {"peptide": ("PEPA", "PEPB"), "precursor": ("PEPA_2", "PEPB_2")}[level]
    collapsed = matrix.loc[list(features), ["run_1.raw", "run_2.raw"]].to_numpy(dtype=float)
    assert collapsed.tolist() == [[700.0, 900.0], [500.0, 800.0]], collapsed.tolist()
def test_the_unstable_rule_really_is_unstable() -> None:
    rows = [
        {"Precursor.Id": "PEP_2", "File.Name": "r1", "Precursor.Quantity": 100.0},
        {"Precursor.Id": "PEP_2", "File.Name": "r1", "Precursor.Quantity": 900.0},
    ]
    forward = pd.DataFrame(rows)
    reversed_ = pd.DataFrame(rows[::-1])

    def collapse(frame: pd.DataFrame, rule: str) -> float:
        pivot = frame.pivot_table(
            index="Precursor.Id",
            columns="File.Name",
            values="Precursor.Quantity",
            aggfunc=rule,
        )
        return float(pivot.iloc[0, 0])

    assert collapse(forward, "first") != collapse(reversed_, "first")
    assert collapse(forward, "max") == collapse(reversed_, "max")
