"""Every kinase receives the same regulation-based marker styling."""
import pandas as pd
import numpy as np
import pytest
import subprocess
from pathlib import Path

from proteomicscopylot import notebook_functions as nb
from app.services import phospho_tools
from app.services.r_runtime import detect_r_runtime


def test_uploaded_control_ksea_labels_contrast_without_changing_scores(monkeypatch):
    frame = pd.DataFrame({"Kinase": ["K"], "Log2(Frequency Factor)": [2.], "Adjusted p-value": [.01]})
    monkeypatch.setattr(phospho_tools, "_plotly_html", lambda fig: fig)
    fig = phospho_tools.ksea_uploaded_volcano_html(
        st_results=frame, tnc_results=frame, condition1="A", condition2="B",
        condition1_control="C", condition2_control="D",
    )
    assert "controls: C vs D" in fig.layout.title.text
    assert fig.layout.xaxis.title.text == "Log2(Frequency Factor) (contrast: (A - C) - (B - D))"
    assert [x for trace in fig.data if trace.mode == "markers" for x in trace.x] == [2., 2.]


@pytest.mark.parametrize("implementation", [nb, phospho_tools])
def test_mixed_ksea_formats_and_raw_log2_equivalence(implementation, monkeypatch):
    raw = pd.DataFrame({"Gene Name": ["low", "same", "high"], "Frequency Factor": [.5, 1., 4.],
                        "Adjusted p value": [.01, 1., 0.]})
    logged = pd.DataFrame({"Kinase": ["other"], "Log2(Frequency Factor)": [-2.], "Adjusted p-value": [.02]})
    normalized = implementation._normalize_ksea_results(pd.concat([raw, logged], ignore_index=True))
    assert normalized.Kinase.tolist() == ["low", "same", "high", "other"]
    assert normalized["Log2(Frequency Factor)"].tolist() == [-1., 0., 2., -2.]
    if implementation is nb:
        figure = nb.kinase_library_volcano(raw, logged)
    else:
        monkeypatch.setattr(phospho_tools, "_plotly_html", lambda fig: fig)
        figure = phospho_tools.ksea_uploaded_volcano_html(st_results=raw, tnc_results=logged)
    points = {label: (x, y, trace.name) for trace in figure.data if trace.mode == "markers"
              for label, x, y in zip(trace.text, trace.x, trace.y)}
    assert points["low"] == (-1., 2., "Enriched in down-regulated sites")
    assert points["same"] == (0., 0., "Not significant")
    assert points["high"] == (2., 300., "Enriched in up-regulated sites")
    assert points["other"][0] == -2.
    assert points["other"][1] == pytest.approx(-np.log10(.02))
    assert raw["Frequency Factor"].tolist() == [.5, 1., 4.]


@pytest.mark.parametrize("implementation", [nb, phospho_tools])
@pytest.mark.parametrize("column,value", [
    ("Adjusted p-value", -.2), ("Adjusted p-value", 1.1),
    ("Adjusted p-value", np.inf), ("Adjusted p-value", np.nan),
    ("Adjusted p-value", "bad"), ("Log2(Frequency Factor)", np.inf),
    ("Frequency Factor", 0), ("Frequency Factor", -1),
])
def test_invalid_ksea_values_are_rejected(implementation, column, value):
    frame = pd.DataFrame({"Kinase": ["K"], "Log2(Frequency Factor)": [1.], "Adjusted p-value": [.01]})
    if column == "Frequency Factor":
        frame = frame.drop(columns="Log2(Frequency Factor)")
    frame[column] = value
    with pytest.raises(ValueError):
        implementation._normalize_ksea_results(frame)


@pytest.mark.parametrize("implementation", [nb, phospho_tools])
def test_conflicting_effect_columns_are_rejected_but_equivalent_scales_are_accepted(implementation):
    frame = pd.DataFrame({"Kinase": ["K"], "Log2(Frequency Factor)": [2.],
                          "Frequency Factor": [4.], "Adjusted p-value": [.01]})
    assert implementation._normalize_ksea_results(frame)["Log2(Frequency Factor)"].iloc[0] == 2.
    frame["Frequency Factor"] = 8.
    with pytest.raises(ValueError, match="Conflicting"):
        implementation._normalize_ksea_results(frame)


@pytest.mark.parametrize("implementation", ["notebook", "backend"])
def test_all_kinases_are_plotted_with_uniform_outlines(implementation, monkeypatch):
    frame = pd.DataFrame({"Kinase": ["GRK2", "AKT1", "GRK5", "MAPK1"],
                          "Log₂(Frequency Factor)": [1., 2., -1., 0.],
                          "Adjusted p-value": [.01, .02, .03, .8]})
    if implementation == "notebook":
        fig = nb.kinase_library_volcano(frame.iloc[:2], frame.iloc[2:])
    else:
        monkeypatch.setattr(phospho_tools, "_plotly_html", lambda fig: fig)
        fig = phospho_tools.ksea_uploaded_volcano_html(st_results=frame.iloc[:2], tnc_results=frame.iloc[2:])
    points = [trace for trace in fig.data if trace.mode == "markers"]
    assert sorted(label for trace in points for label in trace.text) == sorted(frame.Kinase)
    assert {trace.name for trace in points} == {
        "Enriched in up-regulated sites", "Enriched in down-regulated sites", "Not significant"
    }
    for trace in points:
        colors = trace.marker.line.color
        widths = trace.marker.line.width
        assert set([colors] if isinstance(colors, str) else colors) == {"black"}
        assert set([widths] if isinstance(widths, (int, float)) else widths) == {.5}


@pytest.mark.requires_r("plotly")
def test_r_kinase_plot_membership():
    runtime = detect_r_runtime()
    script = '''
      source("proteomicscopylot/notebook_functions.R")
      stopifnot(convert_to_centered("AAAAAAAs*AAAAAAA") == "AAAAAAASAAAAAAA")
      stopifnot(convert_to_centered("s*AAAAAAA") == "_______SAAAAAAA")
      stopifnot(convert_to_centered("AAAAAAAt*") == "AAAAAAAT_______")
      stopifnot(convert_to_centered("ACDy*EFG") == "____ACDYEFG____")
      grDevices::pdf(NULL)
      captured <- NULL
      barplot <- function(height, ...) {
        captured <<- height
        graphics::barplot(height, ...)
      }
      sty_plot(data.frame(PTM_Collapse_key=c("P~GENE_S1_1", "P_T2", "junk", NA)))
      stopifnot(identical(as.numeric(captured), c(1, 1, 0, 2)))
      sty_plot(data.frame(PTM_Collapse_key=character()))
      stopifnot(identical(as.numeric(captured), c(0, 0, 0)))
      dcounts <- data.frame(PTM_localization=c(.99, .5, NA, .9),
                           s1=c(10, 0, 20, Inf), s2=c(10, 5, 20, NA))
      mcounts <- data.frame(sample=c("s1", "s2"), condition=c("A", "A"))
      for (logged in c(FALSE, TRUE)) {
        expected <- rbind(c(1, 1), c(as.integer(logged), 1), c(1, 1))
        stopifnot(all(.phossite_coverage_counts(dcounts, mcounts, logged) == expected))
        phossite_coverage_plot(dcounts, mcounts, is_log2=logged)
        stopifnot(all(captured == expected))
        phossite_coverage_plot_summary(dcounts, mcounts, is_log2=logged)
        stopifnot(all(captured[, 1] == rowMeans(expected)))
      }
      rm(barplot)
      grDevices::dev.off()
      d <- data.frame(Kinase=c("GRK2", "AKT1", "GRK5", "MAPK1"), check.names=FALSE)
      d[["Log2(Frequency Factor)"]] <- c(1, 2, -1, 0)
      d[["Adjusted p-value"]] <- c(.01, .02, .03, .8)
      traces <- plotly::plotly_build(kinase_library_volcano(d[1:2,], d[3:4,]))$x$data
      stopifnot(setequal(unlist(lapply(traces, function(x) x$text)), d$Kinase))
      stopifnot(all(vapply(traces, function(x) all(x$marker$line$color == "black"), logical(1))))
      stopifnot(all(vapply(traces, function(x) all(x$marker$line$width == .5), logical(1))))
      raw <- data.frame("Gene Name"=c("low", "same", "high"), "Frequency Factor"=c(.5, 1, 4),
                        "Adjusted p value"=c(.01, 1, 0), check.names=FALSE)
      normalized <- .normalize_ksea_results(raw)
      stopifnot(identical(normalized$frequency_factor, c(-1, 0, 2)))
      stopifnot(identical(normalized$Kinase, c("low", "same", "high")))
      mixed <- plotly::plotly_build(ksea_volcano(raw, d[1,,drop=FALSE]))$x$data
      stopifnot(setequal(unlist(lapply(mixed, function(x) x$text)), c("low", "same", "high", "GRK2")))
      high <- Filter(function(x) "high" %in% x$text, mixed)[[1]]
      stopifnot(high$y[match("high", high$text)] == 300)
      for (bad in c(-.2, 1.1, Inf, NA, NaN)) {
        invalid <- raw
        invalid[["Adjusted p value"]][1] <- bad
        stopifnot(inherits(try(.normalize_ksea_results(invalid), silent=TRUE), "try-error"))
      }
      for (bad in c(0, -1, Inf, NA)) {
        invalid <- raw
        invalid[["Frequency Factor"]][1] <- bad
        stopifnot(inherits(try(.normalize_ksea_results(invalid), silent=TRUE), "try-error"))
      }
      both <- raw
      both[["Log2(Frequency Factor)"]] <- c(-1, 0, 2)
      stopifnot(identical(.normalize_ksea_results(both)$frequency_factor, c(-1, 0, 2)))
      both[["Log2(Frequency Factor)"]][1] <- 5
      stopifnot(inherits(try(.normalize_ksea_results(both), silent=TRUE), "try-error"))
    '''
    result = subprocess.run([runtime["executable"], "-e", script],
                            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stderr


KSEA_ALIASES = (
    ("ksea_data_f", "kinase_library_data_f"),
    ("ksea_data_f_control", "kinase_library_data_f_control"),
    ("ksea_volcano", "kinase_library_volcano"),
)


def test_the_ksea_names_remain_aliases_of_the_kinase_library_functions():
    """The workflow is Kinase Library motif enrichment, not KSEA; old notebook
    calls keep working through the aliases in the pip package."""
    for alias, target in KSEA_ALIASES:
        assert getattr(nb, alias) is getattr(nb, target), alias


@pytest.mark.requires_r()
def test_the_r_package_keeps_the_same_ksea_aliases(rscript):
    """The R functions keep the same three old names, bound to the very same
    function objects, so an old R notebook calls the current implementation
    rather than a stale copy or nothing at all."""
    checks = "\n".join(
        f'stopifnot(exists("{alias}", envir = env, inherits = FALSE), '
        f'identical(env${alias}, env${target}))'
        for alias, target in KSEA_ALIASES
    )
    script = (
        "env <- new.env()\n"
        'sys.source("proteomicscopylot/notebook_functions.R", envir = env)\n'
        + checks
    )
    result = subprocess.run([rscript, "-e", script],
                            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stderr


def test_the_points_card_styles_the_app_volcano(monkeypatch):
    """The Points card is shown on this plot, so each of its fields reaches every class.

    The class keeps its own colour; without settings the figure is unchanged
    (size 10, a thin black outline), which the test above pins.
    """
    frame = pd.DataFrame({"Kinase": ["GRK2", "AKT1", "GRK5", "MAPK1"],
                          "Log₂(Frequency Factor)": [1., 2., -1., 0.],
                          "Adjusted p-value": [.01, .02, .03, .8]})
    monkeypatch.setattr(phospho_tools, "_plotly_html", lambda fig: fig)
    settings = {"markerSize": 6, "markerAlpha": 0.4, "markerShape": "diamond",
                "markerEdgeWidth": 1.5, "markerEdgeColor": "#123456"}
    fig = phospho_tools.ksea_uploaded_volcano_html(st_results=frame.iloc[:2], tnc_results=frame.iloc[2:],
                                                   advanced=settings)
    points = [trace for trace in fig.data if trace.mode == "markers"]
    assert len(points) == 3
    for trace in points:
        assert trace.marker.size == 6 and trace.marker.opacity == 0.4
        assert trace.marker.symbol == "diamond"
        assert trace.marker.line.width == 1.5 and trace.marker.line.color == "#123456"
    assert len({trace.marker.color for trace in points}) == 3
