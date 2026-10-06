"""An empty result is an answer, and both renderers have to give it.

"Does anything pass these thresholds?" is a real question, and "no" is a real
answer to it. The static renderer drew an empty figure carrying that sentence.
The interactive one raised, which the route turned into a 400 -- so the same
question, asked with the Type selector one notch over, came back as an error in
the frame with no way to tell a strict threshold from a broken plot.

They now answer identically. The sentence is one constant, so they cannot drift
into saying it differently either.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]

from app.services import phospho_tools
from app.services.phospho_tools import PHOSPROT_REGULATION_EMPTY_MESSAGE


@pytest.fixture
def no_sites_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every threshold is met by nothing, which is the case under test."""
    monkeypatch.setattr(
        phospho_tools,
        "phosprot_regulation_table",
        lambda **kwargs: pd.DataFrame(),
    )


def test_the_static_renderer_says_so_on_the_figure(no_sites_pass: None) -> None:
    png = phospho_tools.phosprot_regulation_png(condition1="A", condition2="B")
    assert png.startswith(b"\x89PNG")


def test_the_interactive_renderer_says_so_too_instead_of_raising(
    no_sites_pass: None,
) -> None:
    html = phospho_tools.phosprot_regulation_html(condition1="A", condition2="B")
    assert PHOSPROT_REGULATION_EMPTY_MESSAGE in html
    assert "plotly" in html.lower()


def test_the_route_returns_a_figure_rather_than_a_400(client) -> None:
    """The 400 is what the user saw as a broken plot.

    Asked of the example project with a fold-change threshold no site reaches,
    so the route takes its real path -- the exported-notebook renderer first --
    rather than a stubbed table.
    """
    response = client.get(
        "/api/plots/phospho/phosprot-regulation.html",
        params={"condition1": "WT", "condition2": "GRK", "log2fcThreshold": 1000},
    )
    assert response.status_code == 200, response.text[:200]
    assert PHOSPROT_REGULATION_EMPTY_MESSAGE in response.text


def test_both_renderers_use_the_same_sentence() -> None:
    """Two spellings of one answer is two answers as far as a reader knows."""
    source = (
        ROOT / "backend" / "app" / "services" / "phospho_tools.py"
    ).read_text(encoding="utf-8")
    assert source.count('"No phosphosites pass the selected') == 1, (
        "the message is a constant; a second literal is a copy that will drift"
    )
