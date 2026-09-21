"""A centred phosphoprotein matrix says "Ratio to Site Median" on every plot.

`robust_site_median` centres each phosphosite on its own across-sample median
before collapsing, so the stored values are ratios to that median, not
abundances -- zero means "typical for this site", not "intensity of 1".

`intensity_unit_label` has always known this, but only three call sites used it.
Seven others wrote "log2 Intensity" by hand, so the intensity histogram, both
boxplot modes, the three imputation diagnostics and the single-protein heatmap
colourbar all put the wrong unit over ratios. That is the *default* aggregation
mode in both the schema and the UI, so it was what most phosphoprotein users saw.

No shipped project is centred, so these build one.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import matplotlib

matplotlib.use("Agg")

from app.services import plot_images as P
from app.services.annotation_store import get_annotation
from app.services.functions import intensity_unit_label
from app.services.viewer_bootstrap import load_viewer_state

SERVICES = ROOT / "backend" / "app" / "services"
RATIO = "Ratio to Site Median"


@pytest.fixture(scope="module")
def loaded():
    load_viewer_state(ROOT / "viewer_config.json")


@contextmanager
def aggregation(mode):
    """Present the stored phosphoprotein matrix as the given collapse mode."""
    annotation = get_annotation("phosprot")
    original = annotation.phosprot_aggregation
    annotation.phosprot_aggregation = mode
    try:
        yield
    finally:
        annotation.phosprot_aggregation = original


@contextmanager
def captured_axes():
    """Every axis the next render creates, so its labels can be read back."""
    seen = []
    real = P._make_fig

    def spy(plt, *args, **kwargs):
        figure, axis = real(plt, *args, **kwargs)
        seen.append(axis)
        return figure, axis

    P._make_fig = spy
    try:
        yield seen
    finally:
        P._make_fig = real


def unit_labels(render, **kwargs) -> set[str]:
    with captured_axes() as axes:
        render(**kwargs)
    return {
        text
        for axis in axes
        for text in (axis.get_xlabel(), axis.get_ylabel())
        if "Intensity" in text or RATIO in text
    }


PLOTS = [
    ("intensity histogram", P.qc_intensity_histogram_plot, {}),
    ("boxplot mean", P.qc_boxplot_plot, {"mode": "Mean"}),
    ("boxplot single", P.qc_boxplot_plot, {"mode": "Single"}),
    ("abundance", P.qc_abundance_plot, {}),
]


@pytest.mark.parametrize("name,render,kwargs", PLOTS, ids=[p[0] for p in PLOTS])
def test_a_centred_matrix_is_never_labelled_intensity(
    loaded, name: str, render, kwargs
) -> None:
    with aggregation("robust_site_median"):
        labels = unit_labels(render, kind="phosprot", **kwargs)
    assert labels, f"{name} drew no unit label at all"
    for label in labels:
        assert RATIO in label, f"{name} labels centred ratios as {label!r}"


@pytest.mark.parametrize("name,render,kwargs", PLOTS, ids=[p[0] for p in PLOTS])
def test_an_uncentred_matrix_is_still_labelled_intensity(
    loaded, name: str, render, kwargs
) -> None:
    """The fix must not relabel the abundances that every other mode holds."""
    with aggregation("sum_ignore_na"):
        labels = unit_labels(render, kind="phosprot", **kwargs)
    assert labels
    for label in labels:
        assert "Intensity" in label and RATIO not in label, (
            f"{name} labels plain abundances as {label!r}"
        )


@pytest.mark.parametrize("kind", ["protein", "phospho"])
def test_the_other_levels_are_untouched(loaded, kind: str) -> None:
    """Only phosphoprotein data can be centred; nothing else may change."""
    with aggregation("robust_site_median"):
        labels = unit_labels(P.qc_intensity_histogram_plot, kind=kind)
    assert labels
    for label in labels:
        assert RATIO not in label, f"{kind} is not a phosphoprotein level"


def test_the_helper_is_the_only_source_of_the_unit() -> None:
    """A hardcoded unit cannot know whether the values are centred.

    This is the invariant; the seven individual fixes are how it is met today.
    """
    offenders = []
    for path in SERVICES.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            if "def intensity_unit_label" in line or "unit = " in line:
                continue
            # Case-insensitively: the two single-protein plots wrote
            # `"log2 intensity"` in lower case and slipped past this check for
            # as long as it matched only the capitalised spelling.
            lowered = line.lower()
            if '"log2 intensity"' in lowered or '"log10 intensity"' in lowered:
                offenders.append(f"{path.name}:{number}")
    assert not offenders, (
        "a unit label is hardcoded instead of using intensity_unit_label(): "
        + ", ".join(offenders)
    )


def test_the_helper_says_what_each_mode_means() -> None:
    assert intensity_unit_label(True) == "log2 Ratio to Site Median"
    assert intensity_unit_label(False) == "log2 Intensity"
    assert intensity_unit_label(True, scale="log10", workflow="Phosphoprotein") == (
        "log10 Phosphoprotein Ratio to Site Median"
    )


def test_the_single_protein_heatmap_colourbar_follows_the_same_rule() -> None:
    """Its label is built away from an axis, so it is checked at the source."""
    text = (SERVICES / "single_protein_tools.py").read_text(encoding="utf-8")
    assert 'cbar_label = intensity_unit_label(_phosprot_values_are_centred(kind))' in text
    assert 'cbar_label = "log2 Intensity"' not in text
    assert 'cbar_label = "Z-score"' in text, "z-scored values are a unit of their own"


# --- the single-protein plots --------------------------------------------------


@contextmanager
def captured_single_protein_axes(monkeypatch):
    """The axes of the next single-protein render.

    Those renderers call `plt.subplots` directly rather than `plot_images._make_fig`,
    so `captured_axes` above does not see them. Intercepting the export instead
    catches the figure at the last moment, fully labelled.
    """
    from app.services import single_protein_tools as S

    seen = []
    real = S._to_png_bytes

    def spy(fig, plt, **kwargs):
        seen.extend(fig.axes)
        return real(fig, plt, **kwargs)

    monkeypatch.setattr(S, "_to_png_bytes", spy)
    yield seen


@contextmanager
def pretend_imputed(kind: str):
    """Offer an `imputed` matrix for a project that ships without one.

    The shipped example is configured with imputation off, so `select_matrix`
    refuses `"imputed"`. Reusing the filtered frame under that name is enough to
    check what a renderer *says* about its source, which is all this is for.
    """
    from types import SimpleNamespace

    annotation = get_annotation(kind)
    original_frame = annotation.imputed_data
    original_record = getattr(annotation, "imputation", None)
    annotation.imputed_data = annotation.filtered_data
    # `select_matrix` wants both the frame and the record that says how it was
    # made, which is the right guard: a frame with no provenance is not an
    # imputed matrix.
    annotation.imputation = SimpleNamespace(mode="quantile")
    try:
        yield
    finally:
        annotation.imputed_data = original_frame
        annotation.imputation = original_record


def _first_feature(kind: str) -> str:
    from app.services.single_protein_tools import single_protein_options

    return single_protein_options(kind, data_source="data")["proteins"][0]


@pytest.mark.parametrize("renderer", ["boxplot", "lineplot"])
def test_the_single_protein_plots_ask_what_the_values_are(loaded, monkeypatch, renderer: str) -> None:
    """These two hardcoded `log2 intensity` while the page's heatmap asked."""
    from app.services import single_protein_tools as S

    feature = _first_feature("phosprot")
    render = (
        S.single_protein_boxplot_plot if renderer == "boxplot" else S.single_protein_lineplot_plot
    )
    argument = "protein" if renderer == "boxplot" else "proteins"
    with aggregation("robust_site_median"), captured_single_protein_axes(monkeypatch) as axes:
        render(kind="phosprot", **{argument: feature if renderer == "boxplot" else [feature]},
               conditions=[], legend=False)
    labels = {axis.get_ylabel() for axis in axes}
    assert labels, f"{renderer} drew no y label"
    for label in labels:
        assert RATIO in label, f"the single-protein {renderer} labels centred ratios {label!r}"


def test_the_boxplot_title_does_not_call_imputed_values_measured(loaded, monkeypatch) -> None:
    """Half those points can be draws from a down-shifted normal."""
    from app.services import single_protein_tools as S

    feature = _first_feature("protein")
    with captured_single_protein_axes(monkeypatch) as axes:
        S.single_protein_boxplot_plot(
            kind="protein", protein=feature, conditions=[], legend=False, data_source="data"
        )
    assert any(axis.get_title().startswith("Measured") for axis in axes)

    with pretend_imputed("protein"), captured_single_protein_axes(monkeypatch) as axes:
        S.single_protein_boxplot_plot(
            kind="protein", protein=feature, conditions=[], legend=False, data_source="imputed"
        )
    titles = [axis.get_title() for axis in axes]
    assert titles and all(not title.startswith("Measured") for title in titles), titles
    assert any(title.startswith("Imputed") for title in titles), titles
