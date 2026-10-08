"""The stored imputation record describes the run well enough to state it later.

The Imputation page shows what the session is actually using, separately from
the preview it draws while you change the settings. After a reload there is no
response to read that from -- only the record saved beside the matrix. So the
record has to carry the shape of the run, not just its parameters: without the
row count the page could not say how many values it filled without imputing
again, which is the thing the split exists to prevent.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]

from app.schemas.annotation import AnnotationImputationInfo
from app.schemas.data_tools import ImputationRunRequest
from app.services.annotation_store import get_annotation
from app.services.data_tools import run_imputation


@pytest.fixture
def restored(example_project):
    """Put the annotation back, so this module leaves no imputed matrix behind."""
    annotation = get_annotation("protein")
    before = (annotation.imputed_data, getattr(annotation, "imputation", None))
    yield
    current = get_annotation("protein")
    current.imputed_data, current.imputation = before


def test_a_run_records_the_shape_of_what_it_imputed(restored) -> None:
    response = run_imputation(ImputationRunRequest(kind="protein"))
    record = get_annotation("protein").imputation
    assert record is not None and record.applied

    assert record.rowCount == response.rows, "the record must state the rows it filled"
    assert record.sampleCount == len(response.sampleColumns)
    assert record.missingBefore == response.missingBefore
    assert record.missingAfter == response.missingAfter
    # Everything the page needs to restate the run without repeating it.
    assert (record.mode, record.qValue, record.adjustStd, record.seed) == (
        response.method,
        response.qValue,
        response.adjustStd,
        response.seed,
    )
    assert record.downShift == response.downShift
    assert record.width == response.width
    assert record.sampleWise == response.sampleWise


def test_the_recorded_counts_are_the_ones_the_page_shows(restored) -> None:
    response = run_imputation(ImputationRunRequest(kind="protein"))
    record = get_annotation("protein").imputation
    values = record.rowCount * record.sampleCount
    filled = record.missingBefore - record.missingAfter
    assert values == response.rows * len(response.sampleColumns)
    assert 0 <= filled <= values
    assert filled > 0, "the shipped example has holes; a run with none proves nothing"


def test_a_record_written_before_the_row_count_existed_still_parses() -> None:
    """Older save states and viewer configs carry the record without it."""
    legacy = AnnotationImputationInfo(
        mode="quantile", applied=True, sampleCount=10, missingBefore=5, missingAfter=0
    )
    assert legacy.rowCount is None
    assert AnnotationImputationInfo().rowCount is None


@pytest.mark.parametrize("method", ["quantile", "numerical"])
def test_imputation_commands_execute_without_result_cache(restored, monkeypatch, method):
    from app.services import data_tools, runtime_cache

    def reject_cache(*args, **kwargs):
        raise AssertionError("State-changing imputation must not use the result cache")

    monkeypatch.setattr(runtime_cache, "cached_call", reject_cache)
    original = data_tools.impute_values_with_diagnostics
    seeds = []

    def counted(**kwargs):
        seeds.append(kwargs["seed"])
        return original(**kwargs)

    monkeypatch.setattr(data_tools, "impute_values_with_diagnostics", counted)
    matrices = []
    for seed in (71, 71, 72):
        response = run_imputation(ImputationRunRequest(kind="protein", method=method, seed=seed))
        stored = get_annotation("protein")
        matrices.append(stored.imputed_data.copy())
        assert stored.imputation.seed == response.seed == seed
        assert stored.imputation.mode == response.method == method
        assert response.missingBefore > response.missingAfter
    assert seeds == [71, 71, 72]
    pd.testing.assert_frame_equal(matrices[0], matrices[1])
    assert not matrices[1].equals(matrices[2])
