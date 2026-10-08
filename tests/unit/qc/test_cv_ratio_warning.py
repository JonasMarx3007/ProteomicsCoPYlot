"""The CV of a ratio is not the CV of an abundance.

`robust_site_median` centres every phosphosite on its own across-sample median
before collapsing to the protein, so a `phosprot` matrix produced that way holds
ratios, not intensities. A coefficient of variation computed from those ratios
is a real number, but it is the spread of a ratio around 1 rather than the
spread of an abundance around its mean, so it cannot be read next to the
protein-level or phosphosite-level CVs on the same page.

Only the backend knows how the frame was made -- the browser sees a matrix of
numbers and nothing else -- so the QC options endpoint says so, and the CV tab
warns in a box under the figure. The flag has to be exact: set for that one
collapse at that one level, and clear for every neighbour, because a warning
that shows up on plain abundances teaches people to ignore it.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from app.services.annotation_store import get_annotation

FLAG = "centredPhosprotValues"


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


def flag_for(client, kind: str) -> bool:
    response = client.get(f"/api/plots/qc/{kind}/options")
    assert response.status_code == 200, response.text[:200]
    payload = response.json()
    assert FLAG in payload, f"the QC options for {kind} do not report {FLAG} at all"
    return payload[FLAG]


def test_a_robust_site_median_phosphoprotein_matrix_is_flagged(client) -> None:
    with aggregation("robust_site_median"):
        assert flag_for(client, "phosprot") is True


@pytest.mark.parametrize("mode", ["sum_ignore_na", "sum_propagate_na", "mean", "uploaded", None])
def test_every_other_collapse_carries_abundances_and_is_not_flagged(client, mode) -> None:
    """The other modes and a direct upload hold intensities; they must not warn."""
    with aggregation(mode):
        assert flag_for(client, "phosprot") is False


@pytest.mark.parametrize("kind", ["protein", "phospho"])
def test_the_neighbouring_levels_are_never_flagged(client, kind: str) -> None:
    """Only a phosphoprotein collapse can centre anything, even while one has."""
    with aggregation("robust_site_median"):
        assert flag_for(client, kind) is False


def test_the_cv_renderer_draws_no_warning_into_the_figure(client, monkeypatch) -> None:
    """The warning is the page's, under the figure -- never in the render.

    A note burned into the PNG travels into every export and every report, where
    it cannot be dismissed or translated. This renders the CV of a centred
    phosphoprotein matrix and reads every text the figure holds when it is
    saved. Where the page puts its box is checked by mounting it:
    frontend/tests/unit/centred-cv-notice.test.tsx.
    """
    import matplotlib.figure
    import matplotlib.text

    from app.services import plot_images

    drawn: list[str] = []
    save = matplotlib.figure.Figure.savefig

    def capture(figure, *args, **kwargs):
        drawn.extend(text.get_text() for text in figure.findobj(matplotlib.text.Text))
        return save(figure, *args, **kwargs)

    monkeypatch.setattr(matplotlib.figure.Figure, "savefig", capture)
    with aggregation("robust_site_median"):
        assert flag_for(client, "phosprot") is True
        png = plot_images.qc_cv_plot("phosprot")
    assert png.startswith(b"\x89PNG")
    assert any(text.strip() for text in drawn), "the figure's texts were not captured"
    everything = "\n".join(drawn).lower()
    for warning in ("not comparable", "ratios to", "ratios, not abundances"):
        assert warning not in everything, f"the CV renderer draws {warning!r} into the figure"
