import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.annotation import ConditionAssignment
from app.services import annotation_processor as processor
from app.services.dataset_store import save_table_dataset


def frame():
    return pd.DataFrame({'ProteinNames': ['P1', 'P2', 'P3'],
                         'A1': [-2., 4., 8.], 'A2': [-1., -3., 16.],
                         'Unused': [-10., -10., -10.]})


def compute(data, uploaded, log2):
    with np.errstate(invalid='ignore'):
        if uploaded:
            return processor.compute_annotation_from_metadata(data,
                pd.DataFrame({'sample': ['A1', 'A2'], 'condition': ['A', 'A']}), log2, 0, 'in at least one group')
        return processor.compute_annotation(data, [ConditionAssignment(name='A', columns=['A1', 'A2'])],
                                            log2, 0, 'in at least one group')


@pytest.mark.parametrize('uploaded', [False, True])
def test_counts_selected_cells_and_rows_without_changing_results(uploaded, monkeypatch):
    data = frame()
    original = data.copy(deep=True)
    result = compute(data, uploaded, False)
    warnings = [w for w in result.warnings if 'negative values across' in w]
    assert warnings == ['3 negative values across 2 rows cannot be log2-transformed. '
                        'They become missing and may later be imputed. Check the data scale or preprocessing.']
    monkeypatch.setattr(processor, '_negative_linear_warning', lambda *args: None)
    baseline = compute(data, uploaded, False)
    pd.testing.assert_frame_equal(result.log2_data, baseline.log2_data)
    pd.testing.assert_frame_equal(result.filtered_data, baseline.filtered_data)
    pd.testing.assert_frame_equal(data, original)


@pytest.mark.parametrize('uploaded', [False, True])
@pytest.mark.parametrize('log2', [False, True])
def test_no_warning_for_log2_negatives_or_nonnegative_linear_samples(uploaded, log2):
    data = frame()
    if not log2:
        data[['A1', 'A2']] = data[['A1', 'A2']].abs()
    result = compute(data, uploaded, log2)
    assert not any('negative values across' in w for w in result.warnings)


def test_missing_zero_and_infinity_are_not_counted_as_negative_measurements():
    data = pd.DataFrame({'A1': [None, 0, -np.inf, np.inf, -2, 'bad']})
    assert processor._negative_linear_warning(data, ['A1'], False).startswith('1 negative values across 1 rows')


def test_annotation_response_contains_warning_for_page():
    save_table_dataset('negative.csv', 'protein', frame())
    with TestClient(app) as client, np.errstate(invalid='ignore'):
        response = client.post('/api/annotations/generate', json={
            'kind': 'protein', 'isLog2Transformed': False,
            'conditions': [{'name': 'A', 'columns': ['A1', 'A2']}], 'filter': {'minPresent': 0}})
    assert response.status_code == 200, response.text
    assert any(w.startswith('3 negative values across 2 rows') for w in response.json()['warnings'])
