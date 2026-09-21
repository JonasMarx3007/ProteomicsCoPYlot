"""Every fold-change label says what the number under it actually is.

The tool's convention is that the first selected condition is the minuend:
`condition1 - condition2`, and for the control variant
`(condition1 - c1control) - (condition2 - c2control)`. `comparison_contrast()`
is the single place that spells this out.

Two places had written it by hand and got the control form backwards -- the KSEA
control volcano's x-axis, and the assistant's own description of the volcano --
so a reader was told the opposite of what was plotted. A label is not cosmetic
here: the sign is the finding.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.main import app
from app.schemas.annotation import AnnotationFilterConfig
from app.services.annotation_store import save_annotation
from app.services.functions import comparison_contrast
from app.services.viewer_bootstrap import load_viewer_state

SERVICES = ROOT / "backend" / "app" / "services"

CONDITIONS = ("Treated", "Untreated", "TreatedCtrl", "UntreatedCtrl")


@pytest.fixture(scope="module")
def four_condition_project():
    """A four-condition dataset with a known, planted control-corrected effect.

    The example project has two conditions, so the control contrast cannot be
    exercised with it at all -- which is why the reversed label survived.
    """
    load_viewer_state(ROOT / "viewer_config.json")
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
    load_viewer_state(ROOT / "viewer_config.json")


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


def test_no_module_spells_a_control_contrast_by_hand() -> None:
    """One definition, or they drift -- which is exactly what happened."""
    offenders = []
    for path in SERVICES.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"\{condition[12]\}\s*-\s*\{condition[12]_control\}", text):
            line = text[: match.start()].count("\n") + 1
            # comparison_contrast's own body is the one place this belongs.
            if path.name == "functions.py" and "def comparison_contrast" in text[
                max(0, match.start() - 400) : match.start()
            ]:
                continue
            offenders.append(f"{path.name}:{line}")
    assert not offenders, (
        "a control contrast is spelled out instead of using comparison_contrast(): "
        + ", ".join(offenders)
    )


# --- the computation --------------------------------------------------------


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
    """It cannot be rendered without four conditions of phosphosite data, so
    this pins the construction rather than the pixels."""
    text = (SERVICES / "phospho_tools.py").read_text(encoding="utf-8")
    block = text[text.index("def ksea_volcano") : ] if "def ksea_volcano" in text else text
    assert "comparison_contrast(" in block
    assert "condition2} - {condition2_control}" not in text, (
        "the reversed hand-written control contrast is back"
    )


# --- and so does the assistant ----------------------------------------------


def test_the_assistant_describes_the_orientation_it_computes() -> None:
    from app.services.assistant_methods import METHODS

    volcano = METHODS["stats.volcano"].lower()
    assert "condition 2 minus condition 1" not in volcano, (
        "the assistant tells the user the opposite of what the tool computes"
    )
    assert "first selected condition minus the second" in volcano
    assert "higher in condition 1" in volcano
