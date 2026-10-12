"""The Q-Q plot answers "are these values normal?" using all of them.

`qqnorm_plot_data` filtered its input to `> 0` before plotting. The matrix it is
fed is the annotated **log2** matrix, where a negative value is an ordinary
intensity below 1, and where a `robust_site_median` phosphoprotein matrix holds
ratios centred on zero -- so roughly half of it was discarded. Discarding the
lower half of a distribution is not a neutral loss: it is the single edit most
likely to make a skewed distribution look normal, on the one plot whose whole
job is to show whether it is.

`notebook_functions.py` and `notebook_functions.R` never filtered, so the
backend also disagreed with both packages on the same numbers. The parity tests
did not catch it because the backend helper has no notebook twin -- the packages
call `scipy.stats.probplot` and `qqnorm` directly.

This file also covers the two smaller claims the surface makes: that the
distribution page reads the QC matrix like every other QC surface, and that when
the plot draws a sample rather than everything, it says so.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]

from app.services import data_tools
from app.services.runtime_cache import invalidate_runtime_cache
from app.services.annotation_store import get_annotation
from app.services.functions import QQ_MAX_POINTS, qqnorm_plot_data
from app.services.analysis_matrix import qc_matrix
from app.services.phosprot_tools import transform_phosprot
from app.services.viewer_bootstrap import load_viewer_state


@pytest.fixture(scope="module")
def project():
    load_viewer_state(ROOT / "tests" / "fixtures" / "viewer_config.json")
    return True


# --- nothing is discarded ----------------------------------------------------


def test_values_at_or_below_zero_are_plotted() -> None:
    """The defect, in its simplest form."""
    values = np.array([-3.0, -1.0, 0.0, 1.0, 3.0])
    result = qqnorm_plot_data(values)
    plotted = [sample for _, sample in result["points"]]
    assert len(plotted) == 5, f"{5 - len(plotted)} values were dropped before plotting"
    assert sorted(plotted) == sorted(values.tolist())


def test_reference_illustration_matches_its_distribution_labels() -> None:
    from matplotlib import pyplot as plt
    from tools.generate_qq_reference import create_figure

    figure = create_figure()
    try:
        assert len(figure.axes) == 3
        for axis in figure.axes:
            points = np.asarray(axis.collections[0].get_offsets())
            assert points.shape == (300, 2)
            assert np.isfinite(points).all()
            assert (np.diff(points, axis=0) > 0).all()
        normal = np.asarray(figure.axes[0].collections[0].get_offsets())
        assert np.corrcoef(normal.T)[0, 1] > 0.999
        heavy = figure.axes[2]
        points = np.asarray(heavy.collections[0].get_offsets())
        line = heavy.lines[0]
        residual = points[:, 1] - np.interp(points[:, 0], line.get_xdata(), line.get_ydata())
        assert residual[0] < 0 < residual[-1]
    finally:
        plt.close(figure)


def test_a_distribution_centred_on_zero_keeps_both_halves() -> None:
    """Half a normal sample is not a normal sample, and would still look like one."""
    rng = np.random.default_rng(20260916)
    values = rng.normal(0.0, 1.0, 4000)
    result = qqnorm_plot_data(values)
    plotted = np.array([sample for _, sample in result["points"]])

    assert plotted.size == values.size
    assert (plotted < 0).sum() > 0.4 * values.size, "the lower half is missing"
    assert np.isclose(plotted.mean(), values.mean())
    assert np.isclose(plotted.min(), values.min())


def test_the_sample_quantiles_are_the_input_in_order() -> None:
    values = np.array([2.5, -7.0, 0.0, 1.25])
    plotted = [sample for _, sample in qqnorm_plot_data(values)["points"]]
    assert plotted == sorted(values.tolist())
    theoretical = [t for t, _ in qqnorm_plot_data(values)["points"]]
    assert theoretical == sorted(theoretical), "quantiles must increase with the sample"


def test_the_fit_line_recovers_the_distribution_it_was_given() -> None:
    """An independent check that the line is the Q-Q line and not a rescaled one."""
    rng = np.random.default_rng(11)
    values = rng.normal(-4.0, 2.5, 20000)
    result = qqnorm_plot_data(values)
    (x0, y0), (x1, y1) = result["fitLine"]
    slope = (y1 - y0) / (x1 - x0)
    intercept = y0 - slope * x0
    assert slope == pytest.approx(2.5, rel=0.05), "slope should recover the SD"
    assert intercept == pytest.approx(-4.0, abs=0.05), "intercept should recover the mean"


def test_non_finite_values_are_still_dropped() -> None:
    """An infinity has no quantile and would poison the fit for every other point."""
    values = np.array([-1.0, 0.0, np.nan, np.inf, -np.inf, 1.0])
    result = qqnorm_plot_data(values)
    plotted = [sample for _, sample in result["points"]]
    assert plotted == [-1.0, 0.0, 1.0]
    assert all(np.isfinite([y for _, y in result["fitLine"]]))


def test_an_all_missing_input_is_empty_rather_than_an_error() -> None:
    result = qqnorm_plot_data(np.array([np.nan, np.nan]))
    assert result == {"points": [], "fitLine": []}


# --- the backend agrees with both packages -----------------------------------


def test_the_backend_plots_what_the_python_package_plots() -> None:
    """`scipy.stats.probplot` keeps every finite value; so must the backend.

    Reads the points the package actually draws rather than trusting a comment.
    """
    import matplotlib

    matplotlib.use("Agg")
    from proteomicscopylot import notebook_functions as nb

    rng = np.random.default_rng(7)
    values = rng.normal(0.0, 1.0, 60)
    frame = pd.DataFrame({"A": values[:30], "B": values[30:]})
    metadata = pd.DataFrame({"sample": ["A", "B"], "condition": ["x", "y"]})

    figure = nb.qqnorm_plot(frame, metadata)
    package_points = np.sort(np.asarray(figure.axes[0].lines[0].get_ydata(), dtype=float))
    backend_points = np.array([sample for _, sample in qqnorm_plot_data(values)["points"]])

    assert package_points.size == backend_points.size, (
        "the backend and the pip package disagree on how many values belong on "
        "the plot"
    )
    assert np.allclose(package_points, backend_points)


# --- real data: the matrix that is centred on zero ----------------------------


def test_a_centred_phosphoprotein_matrix_keeps_all_its_points(project) -> None:
    """The default collapse mode produces ratios; this is what was halved."""
    phospho = get_annotation("phospho")
    assert phospho is not None
    centred = transform_phosprot(
        phospho.source_data,
        phospho.metadata,
        mode="robust_site_median",
        data_scale="log2" if phospho.is_log2_transformed else "linear",
    )
    samples = [s for s in phospho.metadata["sample"].astype(str) if s in centred.columns]
    values = centred[samples].apply(pd.to_numeric, errors="coerce").to_numpy(float).ravel()
    finite = values[np.isfinite(values)]
    assert finite.size and finite.min() < 0 < finite.max()

    plotted = qqnorm_plot_data(finite)["points"]
    assert len(plotted) == finite.size
    negative_share = sum(1 for _, sample in plotted if sample <= 0) / len(plotted)
    assert negative_share > 0.3, (
        f"only {negative_share:.0%} of a matrix centred on zero reached the plot"
    )


# --- the distribution page reads the QC matrix --------------------------------


def test_the_distribution_summary_has_one_source(project) -> None:
    """QC describes the data as annotated; no second resolver, no substitution."""
    assert not hasattr(data_tools, "_best_distribution_source"), (
        "the second distribution resolver is back"
    )
    summary = data_tools.distribution_summary("protein")
    assert summary.sourceUsed == "data"

    frame, _ = qc_matrix("protein")
    sample_columns = [c for c in summary.sampleColumns]
    expected = frame[sample_columns].apply(pd.to_numeric, errors="coerce")
    assert summary.stats.count == int(expected.notna().to_numpy().sum())
    assert summary.stats.missingCount == int(expected.isna().to_numpy().sum())


def test_the_summary_and_the_image_describe_the_same_matrix(project) -> None:
    """They used to be free to differ: one read qc_matrix, the other did not."""
    from app.services.plot_images import log2_qc_frame

    summary = data_tools.distribution_summary("phospho")
    image_frame = log2_qc_frame("phospho")
    qc_frame, _ = qc_matrix("phospho")
    assert image_frame.equals(qc_frame)
    assert summary.stats.count == int(
        qc_frame[summary.sampleColumns].apply(pd.to_numeric, errors="coerce").notna().to_numpy().sum()
    )


def test_a_subsampled_plot_says_it_is_subsampled(project, monkeypatch) -> None:
    """Silent subsampling is a plot that is not of the data it claims to be."""
    rng = np.random.default_rng(3)
    frame = pd.DataFrame({f"S{i}": rng.normal(0, 1, 30) for i in range(1, 5)})
    monkeypatch.setattr(data_tools, "qc_matrix", lambda kind: (frame, pd.DataFrame()))
    monkeypatch.setattr(data_tools, "_get_sample_columns", lambda kind, data: list(frame.columns))
    monkeypatch.setattr(data_tools, "QQ_MAX_POINTS", 25)
    invalidate_runtime_cache("test")

    summary = data_tools.distribution_summary("protein")
    assert len(summary.qqPlot) == 25
    assert summary.warnings, "the plot shows 25 of 120 values and said nothing"
    message = " ".join(summary.warnings)
    assert "25" in message and "120" in message
    invalidate_runtime_cache("test")


def test_nothing_is_said_when_nothing_is_sampled(project, monkeypatch) -> None:
    rng = np.random.default_rng(4)
    frame = pd.DataFrame({f"S{i}": rng.normal(0, 1, 5) for i in range(1, 5)})
    monkeypatch.setattr(data_tools, "qc_matrix", lambda kind: (frame, pd.DataFrame()))
    monkeypatch.setattr(data_tools, "_get_sample_columns", lambda kind, data: list(frame.columns))
    invalidate_runtime_cache("test")

    summary = data_tools.distribution_summary("protein")
    assert len(summary.qqPlot) == 20
    assert summary.warnings == []
    invalidate_runtime_cache("test")


def test_the_threshold_is_defined_once(monkeypatch) -> None:
    """The PNG, the JSON and the default all have to agree on the same number.

    The JSON side is held by the subsampling test above, which lowers the
    shared constant and sees the summary follow it. Here the PNG does the same:
    with the constant lowered to 25, the image has to draw 25 points, which a
    renderer with its own literal threshold would not. The helper's own default
    is read from its signature.
    """
    import inspect

    from app.services import plot_images

    assert QQ_MAX_POINTS == 100_000
    assert inspect.signature(qqnorm_plot_data).parameters["max_points"].default == QQ_MAX_POINTS

    rng = np.random.default_rng(3)
    frame = pd.DataFrame({f"S{i}": rng.normal(0, 1, 30) for i in range(1, 5)})
    monkeypatch.setattr(plot_images, "log2_qc_frame", lambda kind: frame)
    monkeypatch.setattr(plot_images, "_get_sample_columns", lambda kind, data: list(frame.columns))
    monkeypatch.setattr(plot_images, "QQ_MAX_POINTS", 25)
    figures = []
    monkeypatch.setattr(plot_images, "_to_png_bytes", lambda fig, plt, **kw: figures.append(fig) or b"")

    plot_images.distribution_qqnorm_plot("protein")
    points = sum(len(collection.get_offsets()) for collection in figures[-1].axes[0].collections)
    assert points == 25, f"the PNG drew {points} of 120 values instead of the shared limit of 25"
