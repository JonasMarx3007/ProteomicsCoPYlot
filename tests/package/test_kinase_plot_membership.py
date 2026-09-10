"""Every kinase receives the same regulation-based marker styling."""
import pandas as pd
import pytest
import subprocess
from pathlib import Path

from proteomicscopylot import notebook_functions as nb
from app.services import phospho_tools
from app.services.r_runtime import detect_r_runtime


@pytest.mark.parametrize("implementation", ["notebook", "backend"])
def test_all_kinases_are_plotted_with_uniform_outlines(implementation, monkeypatch):
    frame = pd.DataFrame({"Kinase": ["GRK2", "AKT1", "GRK5", "MAPK1"],
                          "Log₂(Frequency Factor)": [1., 2., -1., 0.],
                          "Adjusted p-value": [.01, .02, .03, .8]})
    if implementation == "notebook":
        fig = nb.ksea_volcano(frame.iloc[:2], frame.iloc[2:])
    else:
        monkeypatch.setattr(phospho_tools, "_plotly_html", lambda fig: fig)
        fig = phospho_tools.ksea_uploaded_volcano_html(st_results=frame.iloc[:2], tnc_results=frame.iloc[2:])
    points = [trace for trace in fig.data if trace.mode == "markers"]
    assert sorted(label for trace in points for label in trace.text) == sorted(frame.Kinase)
    assert {trace.name for trace in points} == {"Upregulated", "Downregulated", "Not significant"}
    for trace in points:
        colors = trace.marker.line.color
        widths = trace.marker.line.width
        assert set([colors] if isinstance(colors, str) else colors) == {"black"}
        assert set([widths] if isinstance(widths, (int, float)) else widths) == {.5}


def test_r_kinase_plot_membership():
    runtime = detect_r_runtime()
    if not runtime.get("available"):
        pytest.skip("Rscript unavailable")
    script = '''
      source("proteomicscopylot/notebook_functions.R")
      d <- data.frame(Kinase=c("GRK2", "AKT1", "GRK5", "MAPK1"), check.names=FALSE)
      d[["Log2(Frequency Factor)"]] <- c(1, 2, -1, 0)
      d[["Adjusted p-value"]] <- c(.01, .02, .03, .8)
      traces <- plotly::plotly_build(ksea_volcano(d[1:2,], d[3:4,]))$x$data
      stopifnot(setequal(unlist(lapply(traces, function(x) x$text)), d$Kinase))
      stopifnot(all(vapply(traces, function(x) all(x$marker$line$color == "black"), logical(1))))
      stopifnot(all(vapply(traces, function(x) all(x$marker$line$width == .5), logical(1))))
    '''
    result = subprocess.run([runtime["executable"], "-e", script],
                            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stderr
