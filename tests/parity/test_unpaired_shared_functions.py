"""Shared functions that no test had ever compared across the pipelines.

`test_triplicate_parity` proves the three pipelines expose the same *names*.
`test_cross_implementation` proves the big analyses return the same *numbers*.
Between those two there was a gap: 20 functions present in both shipped packages
that no test in `tests/package`, `tests/r`, `tests/backend` or `examples` ever
called, in either language. A function nothing calls is a function that can
drift in one language for a year without anyone finding out, and these are not
all cosmetic -- the KSEA kinase-tree inputs and the PCA enclosing ellipse are
numbers a reader interprets.

This module closes that gap for the ones that produce numbers. The remaining
untested names are plot renderers and path helpers, listed at the bottom so the
gap stays visible rather than being quietly declared finished.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]

from proteomicscopylot import notebook_functions as nb


# jsonlite carries every R result back to Python.
requires_r = pytest.mark.requires_r("jsonlite")


def run_r(body: str) -> dict:
    """Run R against the package and return the JSON it prints as `out`."""
    from app.services.r_runtime import detect_r_runtime

    script = (
        'suppressWarnings(suppressMessages(source("proteomicscopylot/notebook_functions.R")))\n'
        f"{body}\n"
        "cat(jsonlite::toJSON(out, digits = NA, auto_unbox = TRUE))\n"
    )
    result = subprocess.run(
        [detect_r_runtime()["executable"], "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout[result.stdout.index("{") :])


# --- the PCA confidence ellipse -------------------------------------------------

ELLIPSE_POINTS = [
    [3.10, -1.40],
    [2.05, 0.60],
    [4.80, -2.20],
    [1.20, -0.10],
    [3.90, -3.05],
    [0.40, 1.75],
    [5.30, 0.25],
]


@requires_r
def test_the_pca_ellipse_is_the_same_ellipse_in_both_packages() -> None:
    """A group's ellipse is a visual claim about how tight that group is."""
    python_center, python_axes, python_angle = nb.minimum_enclosing_ellipse(
        np.array(ELLIPSE_POINTS)
    )
    points = ", ".join(f"c({x}, {y})" for x, y in ELLIPSE_POINTS)
    out = run_r(
        f"pts <- rbind({points})\n"
        "e <- minimum_enclosing_ellipse(pts)\n"
        "out <- list(center = e$center, axes = e$axes, angle = e$angle)"
    )
    np.testing.assert_allclose(python_center, out["center"], rtol=0, atol=1e-9)
    np.testing.assert_allclose(python_axes, out["axes"], rtol=0, atol=1e-9)
    assert abs(float(python_angle) - float(out["angle"])) < 1e-9


def test_the_backend_draws_the_same_ellipse_as_the_packages() -> None:
    import matplotlib

    matplotlib.use("Agg")
    from app.services.plot_images import _minimum_enclosing_ellipse

    points = np.array(ELLIPSE_POINTS)
    backend = _minimum_enclosing_ellipse(points)
    package = nb.minimum_enclosing_ellipse(points)
    np.testing.assert_allclose(backend[0], package[0], rtol=0, atol=1e-12)
    np.testing.assert_allclose(backend[1], package[1], rtol=0, atol=1e-12)
    assert abs(float(backend[2]) - float(package[2])) < 1e-12


@pytest.mark.parametrize(
    "name,points",
    [
        ("two of three samples identical", [[1.0, 1.0], [1.0, 1.0], [2.0, 3.0]]),
        ("three samples collinear", [[0.0, 0.0], [1.0, 1.0], [2.0, 2.0]]),
    ],
)
def test_a_degenerate_group_is_skipped_rather_than_crashing_the_figure(
    name: str, points: list[list[float]]
) -> None:
    """One group without an ellipse must not cost the whole plot.

    Khachiyan's algorithm needs the group to span the plane. Three points that
    do not -- two identical samples, or three on a line -- make the scatter
    matrix singular, but the raw solver need not raise on every numerical stack.
    The call sites used to count
    points rather than check rank, so the whole PCA figure failed with a 500
    rather than losing one ellipse.

    `fitted_group_ellipse` checks the geometry before fitting, and every call
    site can still draw the remaining groups and points.
    """
    array = np.array(points)
    assert nb.fitted_group_ellipse(array) is None


@requires_r
@pytest.mark.parametrize("scale", [1e-12, 1.0, 1e12])
@pytest.mark.parametrize("points,skipped", [
    ([[1., 1.], [1., 1.], [2., 3.]], True),
    ([[0., 0.], [1., 1.], [2., 2.]], True),
    ([[0., 0.], [1., 1e-9], [2., 2e-9], [3., 1e-9]], True),
    (ELLIPSE_POINTS, False),
])
def test_ellipse_guard_agrees_across_all_pipelines_and_scales(points, skipped, scale):
    from app.services.plot_images import fitted_group_ellipse

    array = (np.array(points) + [1000., -2000.]) * scale
    backend = fitted_group_ellipse(array)
    notebook = nb.fitted_group_ellipse(array)
    assert (backend is None) == skipped
    assert (notebook is None) == skipped
    rows = ",".join(f"c({x:.17g},{y:.17g})" for x, y in array)
    result = run_r(
        f"fit <- fitted_group_ellipse(rbind({rows}))\n"
        "out <- if (is.null(fit)) list(skipped=TRUE) else "
        "list(skipped=FALSE, center=fit$center, axes=fit$axes, angle=fit$angle)"
    )
    assert result["skipped"] == skipped
    if not skipped:
        for fit in (notebook, (result["center"], result["axes"], result["angle"])):
            np.testing.assert_allclose(np.asarray(fit[0]) / scale, backend[0] / scale, atol=1e-8, rtol=0)
            np.testing.assert_allclose(np.asarray(fit[1]) / scale, backend[1] / scale, atol=1e-8, rtol=0)
            assert abs((float(fit[2]) - backend[2] + 90) % 180 - 90) < 1e-7


def test_ellipse_solver_has_a_finite_iteration_budget():
    from app.services.plot_images import _minimum_enclosing_ellipse

    for solve in (_minimum_enclosing_ellipse, nb.minimum_enclosing_ellipse):
        with pytest.raises(ValueError, match="did not converge"):
            solve(np.array(ELLIPSE_POINTS), tol=-1)


def test_a_nearly_degenerate_group_is_skipped_rather_than_drawn_as_a_line() -> None:
    """An ellipse of zero width reads as a region of zero area, not as none."""
    points = np.array([[0.0, 0.0], [1.0, 1e-9], [2.0, 2e-9], [3.0, 1e-9]])
    _, axes, _ = nb.minimum_enclosing_ellipse(points)
    assert min(axes) < 1e-6, "expected the collapsed axis this test is about"
    assert nb.fitted_group_ellipse(points) is None


def test_a_healthy_group_still_gets_its_ellipse() -> None:
    """The guard must refuse the degenerate case and nothing else."""
    fit = nb.fitted_group_ellipse(np.array(ELLIPSE_POINTS))
    assert fit is not None
    center, axes, angle = fit
    raw = nb.minimum_enclosing_ellipse(np.array(ELLIPSE_POINTS))
    np.testing.assert_allclose(center, raw[0], rtol=0, atol=1e-12)
    np.testing.assert_allclose(axes, raw[1], rtol=0, atol=1e-12)
    assert abs(float(angle) - float(raw[2])) < 1e-12


def test_the_backend_and_the_package_skip_the_same_groups() -> None:
    """A figure drawn in a notebook and in the app must lose the same ellipses."""
    import matplotlib

    matplotlib.use("Agg")
    from app.services.plot_images import fitted_group_ellipse

    degenerate = np.array([[0.0, 0.0], [1.0, 1.0], [2.0, 2.0]])
    assert fitted_group_ellipse(degenerate) is None
    assert nb.fitted_group_ellipse(degenerate) is None
    assert fitted_group_ellipse(np.array(ELLIPSE_POINTS)) is not None
    assert nb.fitted_group_ellipse(np.array(ELLIPSE_POINTS)) is not None


@requires_r
def test_the_r_package_skips_the_same_groups_too() -> None:
    points = ", ".join(f"c({x}, {y})" for x, y in ELLIPSE_POINTS)
    out = run_r(
        f"healthy <- rbind({points})\n"
        "collinear <- rbind(c(0, 0), c(1, 1), c(2, 2))\n"
        "identical_pair <- rbind(c(1, 1), c(1, 1), c(2, 3))\n"
        "out <- list(\n"
        "  healthy = !is.null(fitted_group_ellipse(healthy)),\n"
        "  collinear = is.null(fitted_group_ellipse(collinear)),\n"
        "  identical_pair = is.null(fitted_group_ellipse(identical_pair))\n"
        ")"
    )
    assert out["healthy"] is True
    assert out["collinear"] is True
    assert out["identical_pair"] is True


def test_the_skip_notice_names_the_groups_and_never_reaches_the_figure() -> None:
    """The message is for the notice under the plot, not for the plot."""
    one = nb.ellipse_skip_message(["Control"])
    many = nb.ellipse_skip_message(["Control", "Treated"])
    assert "Control" in one and "group Control" in one
    assert "groups Control, Treated" in many
    assert "points themselves are unaffected" in one
    assert nb.ellipse_skip_message([]) == ""
    assert nb.ellipse_skip_message(["", "  "]) == ""


@requires_r
def test_both_packages_word_the_skip_notice_the_same_way() -> None:
    out = run_r(
        'out <- list(one = ellipse_skip_message(c("Control")), '
        'many = ellipse_skip_message(c("Control", "Treated")), '
        "empty = ellipse_skip_message(character(0)))"
    )
    assert out["one"] == nb.ellipse_skip_message(["Control"])
    assert out["many"] == nb.ellipse_skip_message(["Control", "Treated"])
    assert out["empty"] == ""


# --- the KSEA kinase-tree inputs ------------------------------------------------

KSEA_ST = pd.DataFrame(
    {
        "Gene Name": ["AKT1", "MAPK1"],
        "Adjusted p-value": [0.001, 0.5],
        "Log₂(Frequency Factor)": [1.5, -0.25],
    }
)
KSEA_TNC = pd.DataFrame(
    {
        "Gene Name": ["SRC", "ABL1"],
        "Adjusted p-value": [0.0, 1.0],
        "Log₂(Frequency Factor)": [-2.0, 0.0],
    }
)


def test_a_zero_adjusted_p_becomes_a_finite_height_not_infinity() -> None:
    """The tree plots -log10(adj p); an exact zero would be an infinite bar."""
    out = nb.kinase_tree_data_pval(KSEA_ST, KSEA_TNC)
    heights = out["-log10(adj_pval)"].to_numpy(float)
    assert np.isfinite(heights).all(), heights
    assert out.loc[out["Gene Name"] == "SRC", "-log10(adj_pval)"].iloc[0] == 300.0
    assert out.loc[out["Gene Name"] == "ABL1", "-log10(adj_pval)"].iloc[0] == 0.0


@requires_r
def test_the_kinase_tree_inputs_agree_across_the_packages() -> None:
    python_pval = nb.kinase_tree_data_pval(KSEA_ST, KSEA_TNC)
    python_fc = nb.kinase_tree_data_fc(KSEA_ST, KSEA_TNC)
    out = run_r(
        'st <- data.frame(check.names = FALSE, "Gene Name" = c("AKT1", "MAPK1"),'
        ' "Adjusted p-value" = c(0.001, 0.5), "Log\\u2082(Frequency Factor)" = c(1.5, -0.25))\n'
        'tnc <- data.frame(check.names = FALSE, "Gene Name" = c("SRC", "ABL1"),'
        ' "Adjusted p-value" = c(0, 1), "Log\\u2082(Frequency Factor)" = c(-2, 0))\n'
        "p <- kinase_tree_data_pval(st, tnc)\n"
        "f <- kinase_tree_data_fc(st, tnc)\n"
        "out <- list(genes = as.character(p[[1]]), heights = as.numeric(p[[2]]),"
        " fc_genes = as.character(f[[1]]), fc = as.numeric(f[[2]]))"
    )
    assert python_pval["Gene Name"].tolist() == out["genes"]
    np.testing.assert_allclose(
        python_pval["-log10(adj_pval)"].to_numpy(float), out["heights"], rtol=0, atol=1e-9
    )
    assert python_fc["Gene Name"].tolist() == out["fc_genes"]
    np.testing.assert_allclose(
        python_fc.iloc[:, 1].to_numpy(float), out["fc"], rtol=0, atol=1e-12
    )


# --- completeness summaries -----------------------------------------------------

MISS_FRAME = pd.DataFrame(
    {
        "ProteinNames": ["P1", "P2", "P3", "P4"],
        "A1": [1.0, np.nan, 3.0, np.nan],
        "A2": [2.0, np.nan, np.nan, np.nan],
        "B1": [3.0, 4.0, 5.0, np.nan],
    }
)
MISS_META = pd.DataFrame({"sample": ["A1", "A2", "B1"], "condition": ["A", "A", "B"]})


@requires_r
def test_the_overall_missing_percentage_agrees(tmp_path: Path) -> None:
    python_value = nb.all_miss_val(MISS_FRAME, MISS_META, data_scale="log2")
    frame_csv = tmp_path / "miss.csv"
    meta_csv = tmp_path / "miss_meta.csv"
    MISS_FRAME.to_csv(frame_csv, index=False)
    MISS_META.to_csv(meta_csv, index=False)
    out = run_r(
        f'd <- read.csv({json.dumps(str(frame_csv))}, check.names = FALSE)\n'
        f'm <- read.csv({json.dumps(str(meta_csv))}, check.names = FALSE)\n'
        'out <- list(value = all_miss_val(d, m, data_scale = "log2"))'
    )
    assert python_value == pytest.approx(float(out["value"]), abs=1e-9)
    # P4 has no value in any sample, so it says nothing about how complete the
    # samples are and is left out, as in the app; 3 of the other 9 cells are
    # missing. The number is a percentage, rounded to 2 dp.
    assert python_value == pytest.approx(33.33)


@requires_r
def test_the_missing_value_outlier_rule_agrees() -> None:
    frame = pd.DataFrame(
        {"Sample": ["A1", "A2", "B1"], "%_missing_values": [10.0, 50.0, 50.001]}
    )
    python_value = nb.missing_value_outlier(frame, thld=50)
    out = run_r(
        'df <- data.frame(check.names = FALSE, Sample = c("A1", "A2", "B1"),'
        ' "%_missing_values" = c(10, 50, 50.001))\n'
        "out <- list(samples = as.character(missing_value_outlier(df, thld = 50)))"
    )
    samples = out["samples"]
    if isinstance(samples, str):
        samples = [samples]
    assert python_value == samples
    assert python_value == ["B1"], "the threshold is exclusive in both languages"


# --- identifier handling, which decides which column is which sample ------------


@requires_r
@pytest.mark.parametrize(
    "value",
    [
        "20240822_JM_HEK293_WT_1.PG.Log2Quantity",
        "C:\\data\\runs\\Sample_A2.raw.PG.MaxLFQ",
        "Sample B3 Normalized Intensity",
        "plain_sample_name",
        "   padded_name.Quantity   ",
    ],
)
def test_the_sample_suffix_is_stripped_identically(value: str) -> None:
    """Two packages disagreeing here would map values to different samples."""
    python_value = nb.strip_sample_measurement_suffix(value)
    out = run_r(
        f"out <- list(value = strip_sample_measurement_suffix({json.dumps(value)}))"
    )
    assert python_value == out["value"], (
        f"{value!r}: Python gives {python_value!r}, R gives {out['value']!r}"
    )


@requires_r
def test_duplicate_column_names_are_disambiguated_identically() -> None:
    frame = pd.DataFrame([[1, 2, 3, 4]], columns=["A", "A", "B", "A"])
    python_columns = list(nb.make_columns_unique(frame).columns)
    out = run_r(
        'df <- data.frame(check.names = FALSE, A = 1, A = 2, B = 3, A = 4)\n'
        "out <- list(columns = names(make_columns_unique(df)))"
    )
    assert python_columns == out["columns"], (
        f"Python {python_columns} vs R {out['columns']}: a sample would be "
        "addressed by a different name in the two packages"
    )


@requires_r
@pytest.mark.parametrize(
    "value", ["Sample_12", "12abc", "no digits here", "", "a1b2"]
)
def test_the_first_number_in_a_label_is_read_identically(value: str) -> None:
    python_value = nb.extract_number(value)
    out = run_r(f"out <- list(value = extract_number({json.dumps(value)}))")
    assert int(python_value) == int(out["value"]), value


# --- what is still not covered --------------------------------------------------

# Shared functions with no numerical comparison anywhere. Everything left here
# renders a figure or resolves a path, so "same numbers" is not the right test
# for it; a rendering comparison would need image diffing, which this repository
# deliberately does not do. Listed so the gap is visible and shrinking.
STILL_ONLY_VISUAL = frozenset(
    {
        "anova_plot_cluster",
        "correlation_xy_intensity_single",
        "overlap_plot_single",
        "pca_plot_interactive",
        "rt_vs_pred_rt_plot",
        "volcano_plot_h",
        "resource_path",
        "resource_path_manual",
        "format_value",
        "rename_cols",
        # Both build on `volcano_data_f_control`, which IS compared numerically
        # by test_cross_implementation.test_control_volcano_agrees; only the thin
        # selection wrapper around it is untested.
        "different_genes_control",
        "kinase_library_data_f_control",
    }
)


@requires_r
def test_the_uncovered_list_is_honest() -> None:
    """Every name here must still be a function in both packages.

    The pip package is imported and asked; the R package is sourced and asked
    which of the names it defined as functions in its own environment, so a
    base-R function of the same name cannot stand in for a removed one.
    """
    import inspect

    python_missing = {
        name for name in STILL_ONLY_VISUAL
        if not inspect.isfunction(getattr(nb, name, None))
    }
    names = ", ".join(json.dumps(name) for name in sorted(STILL_ONLY_VISUAL))
    out = run_r(
        f"wanted <- c({names})\n"
        "defined <- vapply(wanted, function(name) exists(name, envir = globalenv(), "
        "inherits = FALSE, mode = 'function'), logical(1))\n"
        "out <- list(missing = I(wanted[!defined]))"
    )
    missing = sorted(python_missing | set(out["missing"]))
    assert not missing, (
        f"the uncovered list names functions the packages no longer share: {missing}"
    )
