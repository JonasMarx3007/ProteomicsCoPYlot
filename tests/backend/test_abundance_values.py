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
backend, the Python package and the R package each drew this plot with its own
copy of the arithmetic.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import matplotlib

matplotlib.use("Agg")

from app.services.annotation_store import get_annotation
from app.services.plot_images import (
    _abundance_mean_intensities,
    _get_sample_columns,
)
from app.services.viewer_bootstrap import load_viewer_state

KINDS = ["protein", "phospho", "phosprot"]


@pytest.fixture(scope="module")
def loaded():
    load_viewer_state(ROOT / "viewer_config.json")


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
def test_the_plotted_value_is_log10_of_the_mean(loaded, kind: str) -> None:
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
    loaded, kind: str
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


def test_non_positive_means_are_dropped_rather_than_shifted_into_range(loaded) -> None:
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

def _reintroduces_the_pseudocount(line: str) -> bool:
    """A log10 of a mean with a 1 added to it, on one line, in any language.

    Deliberately not one clever regex: the R form wraps the mean in two nested
    calls (`log10(rowMeans(.numeric_matrix(...), na.rm = TRUE) + 1)`), which a
    `[^)]*` pattern cannot cross, so a pattern that catches the Python form
    silently misses the R one -- which is the copy most likely to be edited
    without the other.
    """
    stripped = line.strip()
    if stripped.startswith(("#", "//")):
        return False
    lowered = stripped.lower()
    if "log10(" not in lowered or "mean" not in lowered:
        return False
    return re.search(r"\+\s*1L?\s*\)", stripped) is not None


PSEUDOCOUNT_EXAMPLES = [
    "        mean_intensities[cond] = np.log10(means + 1)",
    "        means_log = np.log10(means + 1)",
    "    condition_means = np.log10(condition_means + 1)",
    "    values <- log10(rowMeans(.numeric_matrix(data, columns), na.rm = TRUE) + 1)",
    "  condition_means <- log10(rowMeans(.numeric_matrix(data, cols), na.rm = TRUE) + 1)",
]


def test_the_guard_recognises_every_form_the_pseudocount_had() -> None:
    """A guard that cannot see the old code is not a guard."""
    for line in PSEUDOCOUNT_EXAMPLES:
        assert _reintroduces_the_pseudocount(line), line
    for line in [
        "        mean_intensities[cond] = np.log10(means.where(means > 0))",
        "    values <- log10(means)",
        "    bins = np.arange(1, n + 1)",
        "    # log10(x + 1) would plot something else",
    ]:
        assert not _reintroduces_the_pseudocount(line), line

SOURCES = {
    "backend": ROOT / "backend" / "app" / "services" / "plot_images.py",
    "python package": ROOT / "proteomicscopylot" / "notebook_functions.py",
    "R package": ROOT / "proteomicscopylot" / "notebook_functions.R",
}


@pytest.mark.parametrize("name,path", sorted(SOURCES.items()))
def test_no_pipeline_reintroduces_the_pseudocount(name: str, path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    hits = [
        line.strip() for line in source.splitlines() if _reintroduces_the_pseudocount(line)
    ]
    assert not hits, f"{name} is back to plotting log10(mean + 1): {hits}"


@pytest.mark.parametrize("name,path", sorted(SOURCES.items()))
def test_every_pipeline_guards_the_logarithm(name: str, path: Path) -> None:
    """Dropping the pseudocount must not leave log10(0) = -inf in the data."""
    source = path.read_text(encoding="utf-8")
    if path.suffix == ".R":
        assert "means[!is.na(means) & means <= 0] <- NA_real_" in source
        assert (
            "condition_means[!is.na(condition_means) & condition_means <= 0] <- NA_real_"
            in source
        )
    else:
        assert ".where(" in source and "> 0)" in source, (
            f"{name} takes a logarithm without excluding non-positive values"
        )
