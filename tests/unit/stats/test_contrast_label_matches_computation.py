"""Every fold-change label says what the number under it actually is.

The tool's convention is that the first selected condition is the minuend:
`condition1 - condition2`, and for the control variant
`(condition1 - c1control) - (condition2 - c2control)`. `comparison_contrast()`
is the single place that spells this out.

Two places had written it by hand and got the control form backwards -- the Kinase Library
control volcano's x-axis, and the assistant's own description of the volcano --
so a reader was told the opposite of what was plotted. A label is not cosmetic
here: the sign is the finding.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]

from app.main import app
from app.schemas.annotation import AnnotationFilterConfig
from app.services.annotation_store import save_annotation
from app.services.functions import comparison_contrast
from app.services.viewer_bootstrap import load_viewer_state

CONDITIONS = ("Treated", "Untreated", "TreatedCtrl", "UntreatedCtrl")


@pytest.fixture(scope="module")
def four_condition_project():
    """A four-condition dataset with a known, planted control-corrected effect.

    The example project has two conditions, so the control contrast cannot be
    exercised with it at all -- which is why the reversed label survived.
    """
    load_viewer_state(ROOT / "tests" / "fixtures" / "viewer_config.json")
    rng = np.random.default_rng(20260915)
    samples, conditions = [], []
    for condition in CONDITIONS:
        for replicate in range(1, 5):
            samples.append(f"{condition}_{replicate}")
            conditions.append(condition)
    metadata = pd.DataFrame({"sample": samples, "condition": conditions})

    # Feature 0 carries a large, unambiguous control-corrected increase in
    # Treated: (10 - 1) - (10 - 5) = +4. Everything else is noise.
    rows = []
    for index in range(60):
        base = {c: 10.0 for c in CONDITIONS}
        if index == 0:
            base = {"Treated": 10.0, "TreatedCtrl": 1.0, "Untreated": 10.0, "UntreatedCtrl": 5.0}
        values = {}
        for condition in CONDITIONS:
            for replicate in range(1, 5):
                values[f"{condition}_{replicate}"] = base[condition] + rng.normal(0, 0.05)
        rows.append({"ProteinNames": f"P{index:04d}", "GeneNames": f"G{index:04d}", **values})
    frame = pd.DataFrame(rows)

    save_annotation(
        kind="protein",
        source_data=frame,
        metadata=metadata,
        log2_data=frame,
        filtered_data=frame,
        is_log2_transformed=True,
        metadata_source="uploaded",
        filter_config=AnnotationFilterConfig(
            method="at_least_n", minPresent=2, minPercentage=70.0,
            mode="in_at_least_one_group", normalization="none",
        ),
        auto_detected=False,
        warnings=[],
        log2_auto_detected=False,
    )
    yield metadata
    load_viewer_state(ROOT / "tests" / "fixtures" / "viewer_config.json")


REQUEST = {
    "kind": "protein",
    "condition1": "Treated",
    "condition2": "Untreated",
    "condition1Control": "TreatedCtrl",
    "condition2Control": "UntreatedCtrl",
    "testType": "unpaired",
    "pValueThreshold": 0.05,
    "log2fcThreshold": 1.0,
}


# --- the helper is the definition --------------------------------------------


def test_the_helper_puts_condition_one_first() -> None:
    assert comparison_contrast("A", "B") == "A - B"
    assert comparison_contrast("A", "B", "Actrl", "Bctrl") == "(A - Actrl) - (B - Bctrl)"


CONTROLS = (REQUEST["condition1"], REQUEST["condition2"], REQUEST["condition1Control"], REQUEST["condition2Control"])
KINASES = pd.DataFrame({"Kinase": ["K"], "Log2(Frequency Factor)": [1.0], "Adjusted p-value": [0.01]})


def _volcano_axis() -> str:
    """The control volcano drawn by the stats service itself.

    The page's route renders through the notebook capture, which runs its own
    extracted copy of this code; the route's label is checked against the helper
    by `test_the_volcano_axis_names_the_contrast_that_was_computed` below.
    """
    from app.schemas.stats import VolcanoControlRequest
    from app.services import stats_tools

    figure = {}
    original = stats_tools._plotly_html
    try:
        stats_tools._plotly_html = lambda fig: figure.setdefault("fig", fig) and ""
        stats_tools.volcano_html(VolcanoControlRequest(**REQUEST))
    finally:
        stats_tools._plotly_html = original
    return figure["fig"].layout.xaxis.title.text


def _ksea_axis() -> str:
    from app.services import phospho_tools

    figure = {}
    original = phospho_tools._plotly_html
    try:
        phospho_tools._plotly_html = lambda fig: figure.setdefault("fig", fig) and ""
        phospho_tools.ksea_uploaded_volcano_html(
            st_results=KINASES, tnc_results=KINASES,
            condition1=CONTROLS[0], condition2=CONTROLS[1],
            condition1_control=CONTROLS[2], condition2_control=CONTROLS[3],
        )
    finally:
        phospho_tools._plotly_html = original
    return figure["fig"].layout.xaxis.title.text


def _assistant_context() -> str:
    from app.services import ai_functions

    mode = {"source": "volcano_control", "condition1": CONTROLS[0], "condition2": CONTROLS[1],
            "condition1Control": CONTROLS[2], "condition2Control": CONTROLS[3]}
    return ai_functions.stats_volcano_plot("protein", mode=mode)["data"]["text"]


LABEL_PRODUCERS = {
    "volcano axis": ("app.services.stats_tools", _volcano_axis),
    "kinase library volcano axis": ("app.services.phospho_tools", _ksea_axis),
    "assistant volcano context": ("app.services.ai_functions", _assistant_context),
}


@pytest.mark.parametrize("producer", list(LABEL_PRODUCERS))
def test_no_module_spells_a_control_contrast_by_hand(four_condition_project, monkeypatch, producer: str) -> None:
    """One definition, or they drift -- which is exactly what happened.

    The helper is wrapped, where the module took it from, so that its answer is
    marked. Every control-contrast label the tool shows must then carry the
    mark: a label spelled out by hand -- reversed or not -- has none.
    """
    import importlib

    module_name, render = LABEL_PRODUCERS[producer]
    module = importlib.import_module(module_name)

    def marked(*args, **kwargs):
        return "[" + comparison_contrast(*args, **kwargs) + "]"

    monkeypatch.setattr(module, "comparison_contrast", marked, raising=False)
    label = render()
    assert f"[{comparison_contrast(*CONTROLS)}]" in label, (
        f"the {producer} spells the control contrast out instead of using comparison_contrast(): {label[:300]}"
    )


def test_the_control_contrast_is_computed_condition_one_first(four_condition_project) -> None:
    """The planted effect is +4 in (Treated - its control) - (Untreated - its control)."""
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post("/api/stats/volcano-control/run", json=REQUEST)
    assert response.status_code == 200, response.text[:300]
    rows = pd.DataFrame(response.json()["rows"])
    planted = rows.loc[rows["ProteinNames"] == "P0000"].iloc[0]
    assert planted["log2FC"] == pytest.approx(4.0, abs=0.1), (
        f"expected +4 for (10-1)-(10-5); got {planted['log2FC']:.3f}. A negative "
        "value means the contrast is computed the other way round."
    )


def test_the_plain_contrast_is_computed_condition_one_first(four_condition_project) -> None:
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(
            "/api/stats/volcano/run",
            json={k: v for k, v in REQUEST.items() if "Control" not in k},
        )
    assert response.status_code == 200, response.text[:300]
    rows = pd.DataFrame(response.json()["rows"])
    planted = rows.loc[rows["ProteinNames"] == "P0000"].iloc[0]
    # Treated and Untreated are both 10 for the planted feature; the controls
    # differ, so the uncorrected contrast must be ~0.
    assert planted["log2FC"] == pytest.approx(0.0, abs=0.1)


# --- the labels match it -----------------------------------------------------


def test_the_volcano_axis_names_the_contrast_that_was_computed(four_condition_project) -> None:
    with TestClient(app, base_url="http://localhost") as client:
        response = client.get(
            "/api/plots/stats/protein/volcano-control.html",
            params={k: v for k, v in REQUEST.items() if k != "kind"},
        )
    assert response.status_code == 200, response.text[:300]
    expected = comparison_contrast(
        REQUEST["condition1"], REQUEST["condition2"],
        REQUEST["condition1Control"], REQUEST["condition2Control"],
    )
    assert expected in response.text, f"the axis does not name {expected!r}"
    reversed_form = comparison_contrast(
        REQUEST["condition2"], REQUEST["condition1"],
        REQUEST["condition2Control"], REQUEST["condition1Control"],
    )
    assert reversed_form not in response.text, "the axis names the reversed contrast"


def test_the_ksea_volcano_axis_uses_the_shared_helper() -> None:
    """The uploaded Kinase Library volcano names the control contrast condition one first."""
    axis = _ksea_axis()
    assert axis == f"Log2(Frequency Factor) (contrast: {comparison_contrast(*CONTROLS)})", axis
    reversed_form = comparison_contrast(CONTROLS[1], CONTROLS[0], CONTROLS[3], CONTROLS[2])
    assert reversed_form not in axis, "the reversed hand-written control contrast is back"


# --- and so does the assistant ----------------------------------------------


def test_the_assistant_describes_the_orientation_it_computes() -> None:
    from app.services.assistant_methods import METHODS

    volcano = METHODS["stats.volcano"].lower()
    assert "condition 2 minus condition 1" not in volcano, (
        "the assistant tells the user the opposite of what the tool computes"
    )
    assert "first selected condition minus the second" in volcano
    assert "higher in condition 1" in volcano
