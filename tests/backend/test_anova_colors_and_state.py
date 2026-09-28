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
import re
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.schemas.stats import AnovaRequest
from app.services import stats_tools
from app.services.condition_palette_store import (
    build_condition_color_map,
    set_condition_palette,
)
from app.services.stats_tools import anova_png
from app.services.viewer_bootstrap import load_viewer_state

STATS_DIR = ROOT / "frontend" / "src" / "features" / "stats"


def _stats_source() -> str:
    """The statistics section: the page, its panels and their shared helpers."""
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(STATS_DIR.glob("*.ts*")))
RESTORE_UI = ROOT / "frontend" / "src" / "lib" / "restoreUiState.ts"


@pytest.fixture(scope="module")
def loaded():
    load_viewer_state(ROOT / "viewer_config.json")


def _hex_counts(png: bytes) -> set[str]:
    from PIL import Image

    image = Image.open(io.BytesIO(png)).convert("RGB")
    counts = Counter(image.getdata())
    return {"#%02X%02X%02X" % rgb for rgb, _ in counts.most_common(500)}


def test_the_heatmap_paints_conditions_with_the_shared_palette(loaded) -> None:
    palette = build_condition_color_map("protein", ["WT", "GRK"])
    present = _hex_counts(anova_png(AnovaRequest(kind="protein", source="anova")))
    for condition, colour in palette.items():
        assert colour.upper() in present, (
            f"{condition} is {colour} everywhere else but not in the ANOVA heatmap"
        )


def test_a_user_chosen_condition_colour_reaches_the_heatmap(loaded) -> None:
    """The Colors page must govern this plot like any other."""
    set_condition_palette("protein", {"WT": "#00B3A4"})
    try:
        assert build_condition_color_map("protein", ["WT", "GRK"])["WT"] == "#00B3A4"
        present = _hex_counts(anova_png(AnovaRequest(kind="protein", source="anova")))
        assert "#00B3A4" in present, "the chosen colour never reached the figure"
    finally:
        set_condition_palette("protein", {})


def test_the_heatmap_asks_for_the_palette_of_the_level_being_plotted(monkeypatch, loaded) -> None:
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

ANOVA_CONTROLS = (
    "kind",
    "sourceMode",
    "dataSource",
    "identifier",
    "pValueThreshold",
    "useUncorrected",
    "showDendrograms",
    # `showLegend` is deliberately absent: the legend is switched from the
    # advanced panel's Legend card now, not from this page's own state.
    "selectedCluster",
    "nClusters",
    "clusterMethod",
    "postHoc",
)


def test_every_anova_control_is_written_to_the_saved_key() -> None:
    source = _stats_source()
    start = source.index('writePersistedUiState("stats.anova.v1"')
    block = source[start : source.index("});", start)]
    for control in ANOVA_CONTROLS:
        assert control in block, f"{control} is not saved, so it will not restore"


def test_the_saved_key_is_inside_the_captured_prefix() -> None:
    """Save state captures by prefix; a key outside it is silently not saved."""
    prefixes = RESTORE_UI.read_text(encoding="utf-8")
    assert '"pcopylot.ui."' in prefixes
    # persistedUiState namespaces every key under that prefix
    namespaced = (ROOT / "frontend" / "src" / "lib" / "persistedUiState.ts").read_text(
        encoding="utf-8"
    )
    assert 'UI_STATE_PREFIX = "pcopylot.ui."' in namespaced


@pytest.mark.parametrize(
    "control,default",
    [
        ("clusterMethod", '"average"'),
        ("nClusters", "4"),
        ("postHoc", '"none"'),
        ("postHocCondition1", '""'),
        ("postHocCondition2", '""'),
        ("showDendrograms", "true"),
        ("pValueThreshold", "0.05"),
    ],
)
def test_each_control_restores_to_a_default_when_absent(control: str, default: str) -> None:
    """A state file written before a control existed must still restore.

    Every read of `persisted.<control>` has to supply a fallback; without one an
    older save restores `undefined` into the request and the run fails or, worse,
    silently uses whatever the backend defaults to without the UI agreeing.
    """
    source = _stats_source()
    # Exactly this property: `persisted.postHoc` must not match a read of
    # `persisted.postHocCondition1`, which is a different control with a
    # different default.
    pattern = re.compile(rf"persisted\.{re.escape(control)}\b(?![A-Za-z0-9_])")
    assert pattern.search(source), f"{control} is never restored"
    reads = [line for line in source.splitlines() if pattern.search(line)]
    for line in reads:
        guarded = (
            f"?? {default}" in line
            or "restoreClusterMethod(" in line
            or "restoreClusterCount(" in line
            or "restorePValueThreshold(" in line
            or "restoreTestType(" in line
        )
        assert guarded, f"unguarded restore of {control}: {line.strip()}"


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


def test_numeric_controls_survive_a_malformed_saved_value() -> None:
    """NaN from a wrongly-typed old value would reach the backend as a 422."""
    source = _stats_source()
    assert "function restoreNumber(" in source
    assert "Number.isFinite(parsed)" in source
    assert source.count("restoreClusterCount(persisted.nClusters)") == 2, (
        "both panels must restore the cluster count through the guard"
    )
    assert "Number(persisted.nClusters ?? 4)" not in source, (
        "an unguarded numeric restore has reappeared"
    )
    assert "Number(persisted.pValueThreshold ?? 0.05)" not in source


def test_the_guarded_ranges_match_the_schema() -> None:
    """A restored value must not be one the backend would refuse."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        AnovaRequest(kind="protein", nClusters=101)
    with pytest.raises(pydantic.ValidationError):
        AnovaRequest(kind="protein", nClusters=0)
    with pytest.raises(pydantic.ValidationError):
        AnovaRequest(kind="protein", pValueThreshold=0)
    source = _stats_source()
    assert "min: 1, max: 100" in source, "the UI clamp drifted from the schema"
