from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]

from app.services import stats_tools

BASE = {
    "kind": "protein",
    "condition1": "WT",
    "condition2": "GRK",
    "pValueThreshold": 0.05,
    "log2fcThreshold": 1.0,
    "testType": "unpaired",
}


@pytest.mark.parametrize(
    "controls",
    [("", ""), ("WT", ""), ("", "GRK"), ("NOPE", "")],
)
def test_a_blank_control_is_refused_rather_than_ignored(client, controls) -> None:
    """A falsy control means "no control" to the service, which is a contradiction here.

    Leaving a field empty used to return 200 with a result byte-identical to the
    uncorrected volcano. Two wrong controls already raised; one wrong and one
    blank did not, so the likelier mistake was the silent one.
    """
    first, second = controls
    response = client.post(
        "/api/stats/volcano-control/run",
        json={**BASE, "condition1Control": first, "condition2Control": second},
    )
    assert response.status_code == 422, response.text[:200]


@pytest.mark.parametrize(
    ("condition1_control", "condition2_control"),
    [
        ("WT", "Control 2"),
        ("Control 1", "GRK"),
        ("GRK", "Control 2"),
        ("Control 1", "WT"),
        ("Control", "Control"),
    ],
)
def test_control_analysis_requires_four_distinct_conditions(
    client,
    condition1_control: str,
    condition2_control: str,
) -> None:
    response = client.post(
        "/api/stats/volcano-control/run",
        json={
            **BASE,
            "condition1Control": condition1_control,
            "condition2Control": condition2_control,
        },
    )
    assert response.status_code == 422, response.text
    assert "four distinct conditions" in response.text


def test_service_rejects_reused_conditions_without_schema_validation() -> None:
    metadata = pd.DataFrame(
        {
            "sample": ["a1", "a2", "b1", "b2", "c1", "c2", "d1", "d2"],
            "condition": ["A", "A", "B", "B", "C", "C", "D", "D"],
        }
    )
    frame = pd.DataFrame(
        {
            "ProteinNames": ["P1"],
            "a1": [1.0],
            "a2": [1.1],
            "b1": [2.0],
            "b2": [2.1],
            "c1": [0.8],
            "c2": [0.9],
            "d1": [1.5],
            "d2": [1.6],
        }
    )

    with pytest.raises(ValueError, match="four distinct conditions"):
        stats_tools._volcano_dataframe(
            kind="protein",
            condition1="A",
            condition2="B",
            condition1_control="A",
            condition2_control="D",
            identifier="workflow",
            p_value_threshold=0.05,
            log2fc_threshold=0.0,
            test_type="unpaired",
            use_uncorrected=False,
            frame_override=frame,
            metadata_override=metadata,
        )


def test_an_unknown_control_still_reports_the_real_problem(client) -> None:
    response = client.post(
        "/api/stats/volcano-control/run",
        json={**BASE, "condition1Control": "NOPE", "condition2Control": "ALSO_NOPE"},
    )
    assert response.status_code == 400
    assert "annotated samples" in response.text


@pytest.mark.parametrize("suffix", ["volcano-control.png", "volcano-control.html"])
def test_the_image_routes_answer_with_the_models_sentence_not_a_pydantic_dump(client, suffix) -> None:
    """The plot routes build the request model themselves, so its ValidationError
    reached `plot_errors` as a ValueError and went out verbatim: "1 validation
    error for VolcanoControlRequest … input_value={…} … errors.pydantic.dev".
    """
    response = client.get(
        f"/api/plots/stats/protein/{suffix}",
        params={"condition1": "WT", "condition2": "GRK", "condition1Control": "WT", "condition2Control": "Control 2"},
    )
    assert response.status_code == 400, response.text[:200]
    detail = response.json()["detail"]
    assert detail.startswith("Control-corrected volcano analysis requires four distinct conditions")
    assert "validation error" not in detail and "input_value" not in detail and "pydantic" not in detail


def test_validation_messages_strip_the_framing() -> None:
    from pydantic import ValidationError

    from app.api.plot_responses import validation_messages
    from app.schemas.stats import VolcanoControlRequest

    with pytest.raises(ValidationError) as caught:
        VolcanoControlRequest(**BASE, condition1Control="WT", condition2Control="X")
    message = validation_messages(caught.value)
    assert message.startswith("Control-corrected volcano analysis requires four distinct conditions")
    assert "Value error" not in message
