"""The abundance curve plots log10 of the value, and says so truthfully.

The rank-abundance plot's y-axis is labelled `log10 <workflow> Intensity`, or
`log10 <workflow> Ratio to Site Median` on a centred phosphoprotein matrix. It
used to plot `log10(mean + 1)`.

For ordinary MS intensities (1e4 to 1e9) a pseudocount of 1 is invisible in the
middle of the range and grows at the bottom of it: on the shipped HEK293 protein
matrix the lowest-abundance features were up to 0.10 log10 units too high, and
the phosphoprotein matrix up to 0.27 -- a factor of 1.9 on the part of the curve
the plot exists to show.

On a `robust_site_median` phosphoprotein matrix it is not an edge case at all.
Those values are ratios centred on 1, so `log10(x + 1)` is about 0.30 for a
typical site instead of 0, every point moves, and the curve's range compresses
from 0.73 to 0.44 log10 units. The axis named a quantity the figure did not hold.

These tests pin the definition, and pin it in all three pipelines, because the
backend, the Python package and the R functions each drew this plot with its own
copy of the arithmetic.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]

import matplotlib

matplotlib.use("Agg")

from app.services.annotation_store import get_annotation
from app.services.plot_images import (
    _abundance_mean_intensities,
    _get_sample_columns,
)

KINDS = ["protein", "phospho", "phosprot"]


def _linear_means(kind: str) -> pd.DataFrame:
    """Condition means of the uploaded linear intensities, computed here."""
    annotation = get_annotation(kind)
    # The plot reads the normalized, unfiltered, non-imputed matrix on the
    # linear scale, so the expectation is built from that same matrix.
    frame = annotation.log2_data.copy()
    samples = [c for c in annotation.metadata["sample"].astype(str) if c in frame.columns]
    frame[samples] = np.power(2.0, frame[samples].apply(pd.to_numeric, errors="coerce"))
    samples = _get_sample_columns(kind, frame)
    numeric = frame[samples].apply(pd.to_numeric, errors="coerce")
    # The renderer holes out zeros before averaging; a zero intensity is an
    # absence, not a measurement of nothing.
    numeric = numeric.mask(numeric == 0)
    meta = annotation.metadata
    means = {}
    for condition in dict.fromkeys(meta["condition"].astype(str)):
        columns = [
            column
            for column in meta.loc[meta["condition"].astype(str) == condition, "sample"]
            if column in numeric.columns
        ]
        if columns:
            means[condition] = numeric[columns].mean(axis=1, skipna=True)
    return pd.DataFrame(means)


@pytest.mark.parametrize("kind", KINDS)
def test_the_plotted_value_is_log10_of_the_mean(example_project, kind: str) -> None:
    plotted, conditions, _, _ = _abundance_mean_intensities(kind)
    expected = _linear_means(kind)
    assert conditions, f"{kind} produced no conditions"
    for condition in conditions:
        got = plotted[condition].to_numpy(float)
        want = np.log10(expected[condition].where(expected[condition] > 0)).to_numpy(float)
        # The renderer drops rows that are NaN in every condition, so compare on
        # the rows it kept, in its order.
        want = want[plotted.index.to_numpy()]
        both = np.isfinite(got) & np.isfinite(want)
        assert both.sum() > 100, f"{kind}/{condition}: too few finite values to compare"
        assert np.allclose(got[both], want[both], rtol=0, atol=1e-12), (
            f"{kind}/{condition}: plotted value is not log10 of the mean "
            f"(largest difference {np.nanmax(np.abs(got[both] - want[both])):.3g})"
        )


@pytest.mark.parametrize("kind", KINDS)
def test_a_pseudocount_would_be_visible_at_the_bottom_of_the_curve(
    example_project, kind: str
) -> None:
    """Guard against 'the +1 never mattered anyway'."""
    plotted, conditions, _, _ = _abundance_mean_intensities(kind)
    values = plotted[conditions[0]].dropna()
    linear = np.power(10.0, values)
    with_pseudocount = np.log10(linear + 1)
    worst = float((with_pseudocount - values).abs().max())
    assert worst > 0.01, (
        f"{kind}: a pseudocount would shift the lowest point by only {worst:.4g} "
        "log10 units here, so this dataset no longer demonstrates the defect -- "
        "check the claim rather than deleting the test"
    )


def test_non_positive_means_are_dropped_rather_than_shifted_into_range(example_project) -> None:
    """`log10(x + 1)` turned a zero mean into 0.0, a real-looking abundance."""
    plotted, conditions, _, _ = _abundance_mean_intensities("protein")
    for condition in conditions:
        assert np.isfinite(plotted[condition].to_numpy(float)).any()
    # Nothing survives that would be negative or zero on the linear scale: every
    # finite plotted value is log10 of a strictly positive number by definition,
    # so the only way a non-positive mean could appear is as a finite y.
    linear = np.power(10.0, plotted[conditions].to_numpy(float))
    finite = np.isfinite(linear)
    assert (linear[finite] > 0).all()


# --- the same arithmetic in the other two pipelines ---------------------------
#
# Both packages are given a small linear-scale project whose condition means are
# known: sub-unit (0.6), large (2000), zero and negative. log10 of the first two
# is exactly what must be drawn -- a pseudocount moves the first by 0.20 log10
# units -- and the last two have no logarithm and must drop out without the
# language complaining about a logarithm of a non-positive number.

PACKAGE_SAMPLES = ["A1", "A2", "B1", "B2"]
PACKAGE_FRAME = pd.DataFrame({
    "ProteinNames": ["P0", "P1", "P2", "P3"],
    "A1": [0.5, 1000.0, 0.0, -1.0],
    "A2": [0.7, 3000.0, 0.0, -3.0],
    "B1": [2.0, 10.0, 5.0, 8.0],
    "B2": [4.0, 30.0, 5.0, 8.0],
})
PACKAGE_META = pd.DataFrame({"sample": PACKAGE_SAMPLES, "condition": ["A", "A", "B", "B"]})
# Condition A: rows P0 and P1 have positive means; P2 (zero) and P3 (negative) do not.
EXPECTED_A = sorted(np.log10([0.6, 2000.0]))
EXPECTED_B = sorted(np.log10([3.0, 20.0, 5.0, 8.0]))


def test_the_python_package_plots_log10_of_the_mean() -> None:
    """Both abundance plots, with any numpy warning turned into a failure."""
    import warnings

    from proteomicscopylot import notebook_functions as nb

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        figure = nb.abundance_plot(PACKAGE_FRAME, PACKAGE_META, data_scale="linear")
        interactive = nb.interactive_abundance_plot(PACKAGE_FRAME, PACKAGE_META, "A", data_scale="linear")
    plotted = {
        collection.get_label(): sorted(collection.get_offsets()[:, 1].astype(float))
        for collection in figure.axes[0].collections
    }
    assert np.allclose(plotted["A"], EXPECTED_A, rtol=0, atol=1e-12), plotted["A"]
    assert np.allclose(plotted["B"], EXPECTED_B, rtol=0, atol=1e-12), plotted["B"]
    shown = sorted(float(y) for trace in interactive.data for y in trace.y)
    assert np.allclose(shown, EXPECTED_A, rtol=0, atol=1e-12), shown


R_ABUNDANCE_SCRIPT = """
suppressMessages(source("proteomicscopylot/notebook_functions.R"))
options(warn = 2)  # a logarithm of a non-positive mean warns; make it fatal
data <- read.csv(commandArgs(TRUE)[1], check.names = FALSE)
meta <- data.frame(sample = c("A1", "A2", "B1", "B2"), condition = c("A", "A", "B", "B"))
drawn <- list()
points <- function(x, y = NULL, ...) {
  drawn[[length(drawn) + 1]] <<- as.numeric(y)
  graphics::points(x, y, ...)
}
grDevices::pdf(NULL)
abundance_plot(data, meta, data_scale = "linear")
invisible(grDevices::dev.off())
traces <- plotly::plotly_build(interactive_abundance_plot(data, meta, "A", data_scale = "linear"))$x$data
interactive <- unlist(lapply(traces, function(trace) as.numeric(trace$y)))
cat(jsonlite::toJSON(list(static = drawn, interactive = interactive), digits = NA))
"""


@pytest.mark.requires_r("plotly", "jsonlite")
def test_the_r_package_plots_log10_of_the_mean(rscript, tmp_path) -> None:
    import json
    import subprocess

    path = tmp_path / "abundance.csv"
    PACKAGE_FRAME.to_csv(path, index=False)
    result = subprocess.run([rscript, "-e", R_ABUNDANCE_SCRIPT, str(path)], cwd=ROOT,
                            capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    out = json.loads(result.stdout[result.stdout.index("{"):])
    static = sorted(sorted(values) for values in out["static"])
    assert len(static) == 2, out["static"]
    assert any(np.allclose(values, EXPECTED_A, rtol=0, atol=1e-12) for values in static if len(values) == 2), static
    assert any(np.allclose(values, EXPECTED_B, rtol=0, atol=1e-12) for values in static if len(values) == 4), static
    assert np.allclose(sorted(out["interactive"]), EXPECTED_A, rtol=0, atol=1e-12), out["interactive"]
