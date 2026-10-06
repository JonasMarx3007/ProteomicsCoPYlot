from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError
from scipy.stats import ttest_ind

from app.schemas.stats import SimulationRequest
from app.services import stats_tools


SAMPLES_A = ["A_1", "A_2", "A_3", "A_4"]
SAMPLES_B = ["B_1", "B_2", "B_3"]
METADATA = pd.DataFrame(
    {
        "sample": [*SAMPLES_A, *SAMPLES_B],
        "condition": ["A"] * len(SAMPLES_A) + ["B"] * len(SAMPLES_B),
    }
)
FRAME = pd.DataFrame(
    {
        "ProteinNames": ["P1", "P2", "P3"],
        "A_1": [10.0, 20.0, 30.0],
        "A_2": [10.2, 21.0, 29.5],
        "A_3": [9.8, 19.5, 30.5],
        "A_4": [10.1, 20.5, 29.8],
        "B_1": [12.0, 22.0, 31.0],
        "B_2": [20.0, 22.5, 35.0],
        "B_3": [28.0, 21.5, 39.0],
    }
)


def _simulation(test_type: str) -> tuple[SimulationRequest, pd.DataFrame]:
    payload = SimulationRequest(
        kind="protein",
        condition1="A",
        condition2="B",
        testType=test_type,
        useUncorrected=True,
        log2fcThreshold=0.0,
    )
    with patch.object(
        stats_tools,
        "_stats_source",
        return_value=("filtered", FRAME, METADATA, []),
    ):
        result = stats_tools._simulation_dataframe(payload)[2]
    return payload, result


@pytest.mark.parametrize(
    ("test_type", "equal_var"),
    [("unpaired", True), ("unpaired_welch", False)],
)
def test_simulation_dispatch_matches_scipy(
    test_type: str,
    equal_var: bool,
) -> None:
    _, result = _simulation(test_type)
    expected = np.asarray(
        [
            ttest_ind(
                FRAME.loc[row, SAMPLES_A].to_numpy(dtype=float),
                FRAME.loc[row, SAMPLES_B].to_numpy(dtype=float),
                equal_var=equal_var,
            ).pvalue
            for row in FRAME.index
        ]
    )

    assert np.allclose(result["pval"].to_numpy(dtype=float), expected)
    assert (result["test_type"] == test_type).all()


def test_student_and_welch_simulations_do_not_collapse_to_one_result() -> None:
    _, student = _simulation("unpaired")
    _, welch = _simulation("unpaired_welch")

    assert not np.allclose(
        student["pval"].to_numpy(dtype=float),
        welch["pval"].to_numpy(dtype=float),
    )


@pytest.mark.parametrize(
    "removed_test_type",
    ["paired"],
)
def test_simulation_schema_rejects_removed_methods(removed_test_type: str) -> None:
    with pytest.raises(ValidationError):
        SimulationRequest(
            kind="protein",
            condition1="A",
            condition2="B",
            testType=removed_test_type,
        )


def test_simulation_schema_rejects_control_volcano_source() -> None:
    with pytest.raises(ValidationError):
        SimulationRequest(
            kind="protein",
            source="volcano_control",
            condition1="A",
            condition2="B",
        )


def test_simulation_response_reports_the_actual_method() -> None:
    payload = SimulationRequest(
        kind="protein",
        condition1="A",
        condition2="B",
        testType="unpaired_welch",
        useUncorrected=True,
    )
    with patch.object(
        stats_tools,
        "_stats_source",
        return_value=("filtered", FRAME, METADATA, []),
    ):
        response = stats_tools.run_simulation(payload)

    assert response.testType == "unpaired_welch"
