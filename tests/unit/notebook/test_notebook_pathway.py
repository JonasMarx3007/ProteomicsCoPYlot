from notebook_replay_support import set_original_path

import io
import json
import subprocess
import sys
from zipfile import ZipFile

import numpy as np
import pandas as pd
import pytest

from app.services import stats_tools
from app.services.notebook_archive import build_notebook_archive
from app.services.notebook_pathway import render_pathway, pathway_module
from app.services.notebook_snapshots import snapshots
from app.services.session_context import get_session_id


@pytest.fixture
def pathway_database(monkeypatch):
    database = pd.DataFrame([
        ('BP', 'GO:1', 'Test pathway', 'G0;G1;G2;G3;G4;G5;G6;absent'),
        ('BP', 'GO:2', 'Test pathway', 'G14'),
    ], columns=['ontology', 'term', 'description', 'genes'])
    monkeypatch.setattr(stats_tools, 'load_go_db', lambda organism="human": database.copy())
    return database


def options(**changes):
    return dict(kind='protein', pathway='Test pathway', conditions=['A', 'B'], value_type='z',
        include_id=False, header=True, remove_empty=True, cluster_rows=False, cluster_cols=False,
        width_cm=20, height_cm=12, dpi=80, **changes)


@pytest.mark.parametrize('source', ['data', 'filtered', 'imputed'])
@pytest.mark.parametrize('variant', ['plain', 'intensity', 'clustered'])
def test_pathway_export_exact_app_plot(inputs, pathway_database, source, variant):
    kwargs = options(data_source=source)
    if variant == 'intensity':
        kwargs.update(value_type='log2', include_id=True, header=False, remove_empty=False, show_source_count=True)
    if variant == 'clustered':
        kwargs.update(cluster_rows=True, cluster_cols=True, show_source_count=True,
                      advanced={'xTickLabelSize': 7, 'yTickLabelSize': 8, 'conditionLabels': {'A': 'Treatment'}})
    expected = stats_tools.pathway_heatmap_png(**kwargs)
    image, token = render_pathway(**kwargs)
    assert image == expected
    assert getattr(image, 'notice', None) == getattr(expected, 'notice', None)
    recipe = snapshots.get(get_session_id(), token)
    assert recipe.uses_imputed_input == (source == 'imputed')
    if source == 'imputed':
        assert 'seed=77' in recipe.imputation_recipe
    membership = pd.read_parquet(io.BytesIO(recipe.resources['pathway.parquet']))
    assert membership['term'].tolist() == ['GO:1']
    metadata = pd.read_parquet(io.BytesIO(recipe.resources['metadata.parquet']))
    assert set(metadata['condition']) == {'A', 'B'}
    data = pd.read_parquet(io.BytesIO(recipe.resources['input.parquet']))
    assert 'C1' not in data and 'D1' not in data
    assert recipe.provenance['databaseSha256'] == stats_tools._go_database_sha256()


@pytest.mark.parametrize('source', ['data', 'filtered', 'imputed'])
def test_pathway_zip_executes_without_app(inputs, pathway_database, tmp_path, source):
    image, token = render_pathway(**options(data_source=source))
    recipe = snapshots.get(get_session_id(), token)
    _, blob = build_notebook_archive(recipe)
    with ZipFile(io.BytesIO(blob)) as archive:
        archive.extractall(tmp_path)
        name = next(name for name in archive.namelist() if name.endswith('.ipynb'))
    notebook = json.loads((tmp_path / name).read_text())
    cells = '\n'.join(''.join(cell['source']) for cell in notebook['cells'] if cell['cell_type'] == 'code')
    cells = set_original_path(cells, tmp_path)
    replay = subprocess.run([sys.executable, '-I', '-c', "import sys;sys.path.insert(0,'.');\n" + cells],
        cwd=tmp_path, capture_output=True, text=True, timeout=90)
    assert replay.returncode == 0, replay.stderr
    assert (tmp_path / 'reproduced.png').read_bytes() == image
    expected = pd.read_parquet(io.BytesIO(recipe.resources['matrix.parquet']))
    pd.testing.assert_frame_equal(pd.read_csv(tmp_path / 'reproduced_heatmap_matrix.csv', index_col=0),
                                  expected, check_exact=False, rtol=1e-14, atol=1e-14)


def test_gene_median_aggregation_deduplicates_tokens_and_tracks_counts():
    frame = pd.DataFrame({'GeneNames': ['G0;g0;G1', 'g0', 'G1'], 'A1': [2., 8., 6.], 'A2': [4., np.nan, 10.]})
    matrix, counts = pathway_module()._aggregate_pathway_gene_values(frame, gene_column='GeneNames',
        sample_columns=['A1', 'A2'], pathway_genes=['G0', 'g0', 'G1', 'missing'])
    assert matrix.index.tolist() == ['G0', 'G1', 'missing']
    assert matrix.loc['G0'].tolist() == [5., 4.]
    assert matrix.loc['G1'].tolist() == [4., 7.]
    assert counts.tolist() == [2, 2, 0]


@pytest.mark.parametrize('source', ['data', 'imputed'])
def test_phosprot_pathway_preserves_original_imputation_history(phosphosites, monkeypatch, source):
    from app.services.phosprot_tools import aggregate_from_phospho
    database = pd.DataFrame([('BP', 'GO:1', 'Test pathway', 'P0;P1;P2;P3')],
        columns=['ontology', 'term', 'description', 'genes'])
    monkeypatch.setattr(stats_tools, 'load_go_db', lambda organism="human": database)
    annotation = aggregate_from_phospho('mean', source)
    kwargs = options()
    kwargs.update(kind='phosprot', value_type='log2', show_source_count=True)
    image, token = render_pathway(**kwargs)
    assert image == stats_tools.pathway_heatmap_png(**kwargs)
    recipe = snapshots.get(get_session_id(), token)
    assert recipe.provenance['upstreamCollapse'] == annotation.phosprot_lineage.model_dump()
    assert recipe.uses_imputed_input == (source == 'imputed')
    if source == 'imputed':
        assert 'seed=87' in recipe.imputation_recipe


def test_pathway_route_download_and_owner_guard(inputs, pathway_database, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes_plots import router
    from app.services.session_context import set_session_id, reset_session_id
    monkeypatch.setenv('COPYLOT_SESSION_ISOLATION', '1')
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get('/api/plots/stats/protein/pathway-heatmap.png',
            params={'pathway': 'Test pathway', 'conditions': '["A","B"]', 'dpi': 80})
        assert response.status_code == 200, response.text
        token = response.headers['X-CoPYlot-Notebook']
        url = f'/api/plots/notebooks/{token}.zip'
        archive = client.get(url).content
        pathway_database.loc[:, 'genes'] = 'changed'
        assert client.get(url).content == archive
        owner = set_session_id('another-owner')
        try:
            assert client.get(url).status_code == 404
        finally:
            reset_session_id(owner)


def test_missing_imputation_history_keeps_plot_without_notebook(inputs, pathway_database):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes_plots import router
    from app.services.annotation_store import get_annotation

    get_annotation('protein').imputation.seed = None
    expected = stats_tools.pathway_heatmap_png(**options(data_source='imputed'))
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get('/api/plots/stats/protein/pathway-heatmap.png', params={
            'pathway': 'Test pathway', 'conditions': '["A","B"]', 'dataSource': 'imputed',
            'includeId': False, 'dpi': 80})
    assert response.status_code == 200
    assert response.content == expected
    assert 'X-CoPYlot-Notebook' not in response.headers
    assert 'Notebook%20export%20unavailable' in response.headers['X-CoPYlot-Notice']
