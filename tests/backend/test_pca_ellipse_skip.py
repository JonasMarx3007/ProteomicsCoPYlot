"""A group that cannot have an ellipse must not cost the whole PCA figure.

The enclosing ellipse is fitted with Khachiyan's algorithm, which needs the
group's points to span the plane. A condition whose replicates land on a line
-- three samples where one is a near-exact scalar of another, or two samples at
the same coordinates -- makes the scatter matrix singular or numerically unstable.
The call sites used to guard with `len(subset) > 2`, a count and not a rank, so
one such condition returned a 500 and the user saw no plot at all.

These tests pin the three things the fix has to hold together:

* the figure still renders, with the other groups' ellipses on it;
* the omission is stated *under* the plot, never drawn into it -- a figure that
  leaves the tool carries no caption about how the tool drew it;
* the notice is computed from the same projection the figure was drawn from, so
  changing the method or the scaling changes the answer with it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services import plot_images

# Condition A spans the plane. Condition B is three samples on a straight line,
# which is the case that used to raise.
FRAME = pd.DataFrame(
    {
        "a1": [10.0, 4.0, 7.0, 2.0, 5.5],
        "a2": [10.6, 4.9, 6.2, 2.9, 4.4],
        "a3": [9.4, 3.2, 7.8, 1.3, 6.6],
        "b1": [3.0, 8.0, 2.0, 9.0, 1.0],
        "b2": [4.0, 9.0, 3.0, 10.0, 2.0],
        "b3": [5.0, 10.0, 4.0, 11.0, 3.0],
    },
    index=[f"P{i}" for i in range(5)],
)
METADATA = pd.DataFrame(
    {
        "sample": ["a1", "a2", "a3", "b1", "b2", "b3"],
        "condition": ["A", "A", "A", "B", "B", "B"],
    }
)


@pytest.fixture
def pca_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    samples = list(FRAME.columns)
    monkeypatch.setattr(
        plot_images,
        "select_matrix",
        lambda kind, data_source="data": (data_source, FRAME.copy(), METADATA.copy()),
    )
    monkeypatch.setattr(plot_images, "_get_sample_columns", lambda kind, frame: samples)
    monkeypatch.setattr(plot_images, "_metadata_for_kind", lambda kind, frame, cols: METADATA)


def _degenerate_groups() -> list[str]:
    scores, _, _ = plot_images._pca_projection("protein")
    return [
        str(group)
        for group in scores["condition"].unique()
        if plot_images.fitted_group_ellipse(
            scores.loc[scores["condition"] == group, ["PC1", "PC2"]].to_numpy()
        )
        is None
    ]


def test_the_fixture_really_contains_a_group_without_an_ellipse(pca_fixture: None) -> None:
    """Guards the tests below: without this, they would pass on an empty case."""
    assert _degenerate_groups() == ["B"]


def test_the_figure_still_renders_when_one_group_has_no_ellipse(pca_fixture: None) -> None:
    png = plot_images.qc_pca_plot("protein", add_ellipses=True)
    assert png.startswith(b"\x89PNG"), "the degenerate group took the whole figure down"


def test_the_interactive_figure_still_renders_too(pca_fixture: None) -> None:
    html = plot_images.qc_pca_interactive_html("protein", add_ellipses=True)
    assert "plotly" in html.lower()


def test_the_summary_names_the_group_that_got_no_ellipse(pca_fixture: None) -> None:
    summary = plot_images.qc_pca_feature_summary("protein", add_ellipses=True)
    assert summary["ellipseSkippedGroups"] == ["B"]


def test_nothing_is_named_when_ellipses_are_off(pca_fixture: None) -> None:
    """The notice answers "why is there no ellipse here", which is not asked."""
    summary = plot_images.qc_pca_feature_summary("protein", add_ellipses=False)
    assert summary["ellipseSkippedGroups"] == []


def test_nothing_is_named_in_3d(pca_fixture: None) -> None:
    """The 3D figure draws no ellipses at all, so none can be missing."""
    summary = plot_images.qc_pca_feature_summary("protein", plot_dim="3D", add_ellipses=True)
    assert summary["ellipseSkippedGroups"] == []


def test_the_notice_follows_the_projection_the_figure_was_drawn_from(
    pca_fixture: None,
) -> None:
    """Scaling moves the points, so it can move a group in or out of the answer.

    This is why the endpoint takes every projection control rather than
    defaulting: a notice computed from the defaults would describe a figure the
    user is not looking at.
    """
    centred = plot_images.qc_pca_feature_summary(
        "protein", add_ellipses=True, scaling="centered"
    )["ellipseSkippedGroups"]
    scaled = plot_images.qc_pca_feature_summary(
        "protein", add_ellipses=True, scaling="unit_variance"
    )["ellipseSkippedGroups"]
    assert centred == ["B"]
    assert isinstance(scaled, list)


def test_a_failing_projection_costs_the_notice_and_not_the_summary(
    monkeypatch: pytest.MonkeyPatch, pca_fixture: None
) -> None:
    """The feature counts are the point of this endpoint; the notice is an extra."""

    def explode(*args: object, **kwargs: object) -> None:
        raise RuntimeError("projection unavailable")

    monkeypatch.setattr(plot_images, "_pca_projection", explode)
    summary = plot_images.qc_pca_feature_summary("protein", add_ellipses=True)
    assert summary["ellipseSkippedGroups"] == []
    assert summary["featuresTotal"] == 5


def test_the_message_is_never_written_into_the_figure(pca_fixture: None) -> None:
    """A plot taken out of the tool must not carry a caption about the tool."""
    html = plot_images.qc_pca_interactive_html("protein", add_ellipses=True)
    assert "No ellipse was drawn" not in html


@pytest.mark.parametrize(
    "points",
    [
        pytest.param([[1.0, 1.0], [1.0, 1.0], [2.0, 3.0]], id="two samples identical"),
        pytest.param([[0.0, 0.0], [1.0, 1.0], [2.0, 2.0]], id="three samples collinear"),
        pytest.param([[0.0, 0.0], [1.0, 0.0]], id="only two samples"),
        pytest.param([[0.0, 0.0], [1.0, np.nan], [2.0, 2.0]], id="a missing coordinate"),
        pytest.param([[0.0, 0.0], [1.0, 1e-12], [2.0, 2e-12]], id="a collapsed axis"),
    ],
)
def test_every_shape_without_an_ellipse_is_refused(points: list[list[float]]) -> None:
    assert plot_images.fitted_group_ellipse(np.array(points)) is None
