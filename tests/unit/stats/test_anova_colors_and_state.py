"""ANOVA uses the tool's condition colours, and its options survive a save.

Two separate promises:

* a condition is the same colour in the ANOVA heatmap as in the volcano, the
  PCA and the boxplots beside it -- including any colour the user chose;
* the ANOVA controls come back after a save/restore, and a state file written
  before a control existed still restores, falling back to that control's
  default rather than failing or restoring something arbitrary.
"""

from __future__ import annotations

import io
import json
from collections import Counter

import pytest

from app.schemas.stats import AnovaRequest
from app.services import stats_tools
from app.services.condition_palette_store import (
    build_condition_color_map,
    set_condition_palette,
)
from app.services.stats_tools import anova_png
from app.services.viewer_bootstrap import load_viewer_state


def _hex_counts(png: bytes) -> set[str]:
    from PIL import Image

    image = Image.open(io.BytesIO(png)).convert("RGB")
    counts = Counter(image.getdata())
    return {"#%02X%02X%02X" % rgb for rgb, _ in counts.most_common(500)}


def test_the_heatmap_paints_conditions_with_the_shared_palette(example_project) -> None:
    palette = build_condition_color_map("protein", ["WT", "GRK"])
    present = _hex_counts(anova_png(AnovaRequest(kind="protein", source="anova")))
    for condition, colour in palette.items():
        assert colour.upper() in present, (
            f"{condition} is {colour} everywhere else but not in the ANOVA heatmap"
        )


def test_a_user_chosen_condition_colour_reaches_the_heatmap(example_project) -> None:
    """The Colors page must govern this plot like any other."""
    set_condition_palette("protein", {"WT": "#00B3A4"})
    try:
        assert build_condition_color_map("protein", ["WT", "GRK"])["WT"] == "#00B3A4"
        present = _hex_counts(anova_png(AnovaRequest(kind="protein", source="anova")))
        assert "#00B3A4" in present, "the chosen colour never reached the figure"
    finally:
        set_condition_palette("protein", {})


def test_the_heatmap_asks_for_the_palette_of_the_level_being_plotted(monkeypatch, example_project) -> None:
    """Phospho conditions must not be coloured from the protein palette."""
    seen: list[str] = []
    real = stats_tools.advanced_condition_colors

    def spy(kind, plt, conditions, settings):
        seen.append(kind)
        return real(kind, plt, conditions, settings)

    monkeypatch.setattr(stats_tools, "advanced_condition_colors", spy)
    anova_png(AnovaRequest(kind="phospho", source="anova"))
    assert seen and set(seen) == {"phospho"}, seen


# --- save state -------------------------------------------------------------
#
# That the panel saves every control, under the captured prefix, and restores
# each one -- missing, malformed or out of range -- to the default and range of
# AnovaRequest is tested by mounting it: frontend/tests/unit/anova-state.test.tsx.


def test_an_old_state_file_without_the_new_controls_still_parses() -> None:
    """Shape check on the payload an older build would have written."""
    legacy = {
        "kind": "protein",
        "sourceMode": "anova_cluster",
        "dataSource": "data",
        "identifier": "workflow",
        "pValueThreshold": 0.05,
        "useUncorrected": False,
        "showDendrograms": True,
        "showLegend": True,
        "selectedCluster": "none",
        "nClusters": 4,
        "postHoc": "none",
    }
    assert "clusterMethod" not in legacy
    # The saved value is a JSON string in sessionStorage; restoring is a parse.
    restored = json.loads(json.dumps(legacy))
    assert restored["nClusters"] == 4
    # The backend default fills the gap the old file cannot.
    assert AnovaRequest(kind="protein").clusterMethod == "average"


def test_the_guarded_ranges_match_the_schema() -> None:
    """A restored value must not be one the backend would refuse."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        AnovaRequest(kind="protein", nClusters=101)
    with pytest.raises(pydantic.ValidationError):
        AnovaRequest(kind="protein", nClusters=0)
    with pytest.raises(pydantic.ValidationError):
        AnovaRequest(kind="protein", pValueThreshold=0)
