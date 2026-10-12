from notebook_replay_support import set_original_path

import io
import json
import subprocess
import sys
from zipfile import ZipFile

import pandas as pd
import pytest

from app.schemas.stats import AnovaRequest
from app.services import stats_tools
from app.services.notebook_anova import anova_module, render_anova
from app.services.notebook_archive import build_notebook_archive
from app.services.notebook_snapshots import snapshots
from app.services.session_context import get_session_id


@pytest.mark.parametrize('method', ['average', 'ward', 'complete', 'weighted', 'single'])
@pytest.mark.parametrize('source', ['data', 'filtered', 'imputed'])
def test_anova_calculations_match_app(inputs, method, source):
    payload = AnovaRequest(kind='protein', source='anova_cluster', dataSource=source,
        pValueThreshold=1, nClusters=3, clusterMethod=method, useUncorrected=method == 'single',
        postHoc='tukey', postHocCondition1='B', postHocCondition2='A')
    resolved, data, metadata, warnings = stats_tools._stats_source('protein', data_source=source)
    mask = stats_tools._imputation_mask('protein', resolved, data, metadata['sample'].tolist())
    actual = anova_module().calculate_tables(data, metadata, payload.model_dump(), mask)
    expected = stats_tools.run_anova(payload).model_dump()
    actual['warnings'] = warnings + actual['warnings']
    for key in ('rows', 'clusterRows', 'postHocRows'):
        pd.testing.assert_frame_equal(pd.DataFrame(actual.pop(key)), pd.DataFrame(expected.pop(key)))
    assert actual == expected


@pytest.mark.parametrize('source,cluster,posthoc', [
    ('data', None, 'none'), ('filtered', None, 'tukey'), ('imputed', 1, 'tukey')])
def test_anova_standalone_notebook_reproduces_tables_and_heatmap(inputs, tmp_path, source, cluster, posthoc):
    payload = AnovaRequest(kind='protein', source='anova_cluster' if cluster else 'anova',
        dataSource=source, pValueThreshold=1, postHoc=posthoc,
        postHocCondition1='B', postHocCondition2='C', showRowLabels=True, nClusters=3)
    advanced = {'conditionLabels': {'A': 'Treatment'}, 'rowLabelSize': 6, 'rowLabelColor': '#224466'}
    expected = stats_tools.anova_png(payload, selected_cluster=cluster, advanced=advanced)
    actual, token = render_anova(payload, selected_cluster=cluster, advanced=advanced)
    assert actual == expected
    assert getattr(actual, 'notice', None) == getattr(expected, 'notice', None)
    recipe = snapshots.get(get_session_id(), token)
    assert recipe.uses_imputed_input == (source == 'imputed')
    if source == 'imputed':
        assert 'seed=77' in recipe.imputation_recipe
    _, blob = build_notebook_archive(recipe)
    with ZipFile(io.BytesIO(blob)) as archive:
        archive.extractall(tmp_path)
        name = next(name for name in archive.namelist() if name.endswith('.ipynb'))
    notebook = json.loads((tmp_path / name).read_text())
    cells = '\n'.join(''.join(cell['source']) for cell in notebook['cells'] if cell['cell_type'] == 'code')
    cells = set_original_path(cells, tmp_path)
    result = subprocess.run([sys.executable, '-I', '-c', "import sys;sys.path.insert(0,'.');\n" + cells],
        cwd=tmp_path, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / 'reproduced.png').read_bytes() == actual
    if cluster:
        assert (tmp_path / 'reproduced_selected_cluster.csv').exists()


@pytest.mark.parametrize('threshold', [1e-30, 1])
@pytest.mark.parametrize('groups', ['AB', 'ABCD'])
def test_empty_results_and_all_pair_posthoc(inputs, threshold, groups):
    _, data, metadata, _ = stats_tools._stats_source('protein', data_source='data')
    metadata = metadata.loc[metadata['condition'].isin(list(groups))]
    payload = AnovaRequest(kind='protein', source='anova_cluster', pValueThreshold=threshold, postHoc='tukey')
    result = anova_module().calculate_tables(data, metadata, payload.model_dump())
    if threshold < 1:
        assert result['significantCount'] == 0
        assert not result['clusterRows'] and not result['postHocRows']
    elif len(groups) == 2:
        assert not result['postHocRows']
        assert any('two conditions' in message for message in result['warnings'])
    else:
        assert result['postHocRows']
        assert result['postHocComparison'] is None


def test_phosphosite_anova_and_palette_capture(phosphosites):
    payload = AnovaRequest(kind='phospho', pValueThreshold=1, dataSource='imputed')
    content, token = render_anova(payload)
    assert content == stats_tools.anova_png(payload)
    recipe = snapshots.get(get_session_id(), token)
    assert recipe.uses_imputed_input
    assert set(recipe.settings['figure']['condition_palette']) == {'A', 'B'}


def test_anova_does_not_publish_changed_session(inputs, monkeypatch):
    from app.services import runtime_cache
    versions = iter([1, 2])
    monkeypatch.setattr(runtime_cache, 'runtime_cache_version', lambda: next(versions))
    content, token = render_anova(AnovaRequest(kind='protein', pValueThreshold=1))
    assert content.startswith(b'\x89PNG')
    assert token == ''


@pytest.mark.parametrize('cluster', [None, 1])
def test_anova_routes_freeze_full_results_and_enforce_owner(inputs, monkeypatch, cluster):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes_plots import router
    from app.services.annotation_store import get_annotation
    from app.services.session_context import set_session_id, reset_session_id
    monkeypatch.setenv('COPYLOT_SESSION_ISOLATION', '1')
    app = FastAPI()
    app.include_router(router)
    payload = AnovaRequest(kind='protein', source='anova_cluster', pValueThreshold=1,
        postHoc='tukey', postHocCondition1='B', postHocCondition2='C', nClusters=3)
    params = payload.model_dump(exclude={'kind'})
    if cluster is not None:
        params['selectedCluster'] = cluster
    with TestClient(app) as client:
        response = client.get('/api/plots/stats/protein/anova.png', params=params)
        assert response.status_code == 200, response.text
        token = response.headers['X-CoPYlot-Notebook']
        url = f'/api/plots/stats/protein/anova-tables?snapshot={token}'
        captured = client.get(url)
        assert captured.status_code == 200, captured.text
        expected = json.loads(stats_tools.run_anova(payload).model_dump_json())
        assert captured.json() == expected
        first_zip = client.get(f'/api/plots/notebooks/{token}.zip').content
        get_annotation('protein').log2_data.loc[:, 'A1'] = 999.
        assert client.get(url).json() == expected
        assert client.get(f'/api/plots/notebooks/{token}.zip').content == first_zip
        assert client.get(url.replace('/protein/', '/phospho/')).status_code == 409
        other = set_session_id('another-owner')
        try:
            assert client.get(url).status_code == 404
            assert client.get(f'/api/plots/notebooks/{token}.zip').status_code == 404
        finally:
            reset_session_id(other)


def test_anova_empty_threshold_route_still_exports_table(inputs):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes_plots import router
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get('/api/plots/stats/protein/anova.png?source=anova_cluster&pValueThreshold=1e-30')
        assert response.status_code == 200, response.text
        token = response.headers['X-CoPYlot-Notebook']
        tables = client.get(f'/api/plots/stats/protein/anova-tables?snapshot={token}').json()
        assert tables['significantCount'] == 0
        assert tables['rows'] and not tables['clusterRows']


def test_anova_snapshot_serializes_infinite_f_like_normal_api(inputs):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes_plots import router
    from app.services.annotation_store import get_annotation
    frame = get_annotation('protein').log2_data
    for group_index, group in enumerate('ABCD'):
        frame.loc[0, [f'{group}{i}' for i in range(1, 5)]] = float(group_index)
    get_annotation('protein').source_data = frame.copy()
    _, token = render_anova(AnovaRequest(kind='protein', pValueThreshold=1e-30))
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get(f'/api/plots/stats/protein/anova-tables?snapshot={token}')
        assert response.status_code == 200, response.text
        row = next(row for row in response.json()['rows'] if row['ProteinNames'] == 'P0')
        # No variation within any condition: no p-value (as the live API), and
        # the infinite F is serialised as null, not as a JSON error.
        assert row['pval'] is None and row['significance'] == 'Unavailable'
        assert row['f_statistic'] is None
    recipe = snapshots.get(get_session_id(), token)
    table = pd.read_parquet(io.BytesIO(recipe.resources['rows.parquet']))
    assert table.loc[table['ProteinNames'] == 'P0', 'f_statistic'].item() == float('inf')


@pytest.mark.parametrize('source', ['data', 'imputed'])
def test_phosprot_anova_preserves_historical_imputation(phosphosites, source):
    from app.services.phosprot_tools import aggregate_from_phospho
    annotation = aggregate_from_phospho('mean', source)
    payload = AnovaRequest(kind='phosprot', pValueThreshold=1)
    image, token = render_anova(payload)
    assert image == stats_tools.anova_png(payload)
    recipe = snapshots.get(get_session_id(), token)
    assert recipe.provenance['upstreamCollapse'] == annotation.phosprot_lineage.model_dump()
    assert recipe.uses_imputed_input == (source == 'imputed')
    if source == 'imputed':
        assert 'seed=87' in recipe.imputation_recipe


def test_anova_unknown_history_keeps_plot_available(phosphosites):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes_plots import router
    from app.services.phosprot_tools import aggregate_from_phospho
    annotation = aggregate_from_phospho('mean', 'imputed')
    annotation.phosprot_lineage.imputation.seed = None
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get('/api/plots/stats/phosprot/anova.png?pValueThreshold=1')
        assert response.status_code == 200, response.text
        assert response.content.startswith(b'\x89PNG')
        assert 'X-CoPYlot-Notebook' not in response.headers
        assert 'X-CoPYlot-Notice' in response.headers
