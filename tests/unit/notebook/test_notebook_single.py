from notebook_replay_support import set_original_path

import io
import json
import subprocess
import sys
from zipfile import ZipFile

import pandas as pd
import pytest

from app.services import single_protein_tools as single
from app.services.notebook_single import render_box, render_line, render_heatmap
from app.services.notebook_archive import build_notebook_archive
from app.services.notebook_qc import snapshots
from app.services.session_context import get_session_id
from test_notebook_volcano import inputs
from test_notebook_phosprot import phosphosites


@pytest.mark.parametrize('source', ['data', 'filtered', 'imputed'])
@pytest.mark.parametrize('value_type,cluster', [('log2', False), ('z', True)])
def test_heatmap_exact_standalone_replay(phosphosites, tmp_path, source, value_type, cluster):
    options = dict(kind='phospho', protein='P0', conditions=['A', 'B'], identifier='genes' if cluster else 'workflow',
        filter_m1=False, cluster_rows=cluster, cluster_cols=cluster, value_type=value_type,
        include_id=True, data_source=source, dpi=80, cmap_name='viridis',
        advanced={'titleElement': {'text': 'Selected sites', 'bold': True}, 'xTickLabelRotation': 35})
    image, token = render_heatmap(**options)
    expected = single.single_protein_heatmap_plot(**options)
    assert image == expected
    assert getattr(image, 'notice', None) == getattr(expected, 'notice', None)
    recipe = snapshots.get(get_session_id(), token)
    preparation = {k: options[k] for k in ('kind', 'protein', 'conditions', 'identifier', 'include_id',
        'data_source', 'filter_m1', 'cluster_rows', 'cluster_cols', 'value_type')}
    pd.testing.assert_frame_equal(pd.read_parquet(io.BytesIO(recipe.resources['table.parquet'])),
                                  single.single_protein_heatmap_table(**preparation), check_flags=False)
    assert recipe.uses_imputed_input == (source == 'imputed')
    _, blob = build_notebook_archive(recipe)
    with ZipFile(io.BytesIO(blob)) as archive:
        archive.extractall(tmp_path)
        name = next(n for n in archive.namelist() if n.endswith('.ipynb'))
    notebook = json.loads((tmp_path / name).read_text())
    cells = '\n'.join(''.join(c['source']) for c in notebook['cells'] if c['cell_type'] == 'code')
    cells = set_original_path(cells, tmp_path)
    run = subprocess.run([sys.executable, '-I', '-c', "import sys;sys.path.insert(0,'.');\n" + cells],
        cwd=tmp_path, capture_output=True, text=True, timeout=90)
    assert run.returncode == 0, run.stderr
    assert (tmp_path / 'reproduced.png').read_bytes() == image


def test_heatmap_m1_and_constant_row_preservation(phosphosites):
    from app.services.annotation_store import get_annotation
    frame = get_annotation('phospho').log2_data
    frame.loc[:2, 'PTM_Collapse_key'] = ['P0_S1_M1', 'P0_S2_M1', 'P0_S3_M2']
    frame.loc[0, [f'{g}{i}' for g in 'AB' for i in range(1, 5)]] = 10.
    get_annotation('phospho').source_data = frame.copy()
    options = dict(kind='phospho', protein='P0', conditions=[], value_type='z', dpi=80)
    image, token = render_heatmap(**options)
    assert image == single.single_protein_heatmap_plot(**options)
    table = pd.read_parquet(io.BytesIO(snapshots.get(get_session_id(), token).resources['table.parquet']))
    assert table.PTM_Collapse_key.tolist() == ['P0_S1_M1', 'P0_S2_M1']
    assert (table.iloc[0, 2:] == 0).all()


def test_heatmap_snapshot_selection_and_ownership(phosphosites, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes_plots import router
    from app.services.annotation_store import get_annotation
    from app.services.session_context import set_session_id, reset_session_id
    monkeypatch.setenv('COPYLOT_SESSION_ISOLATION', '1')
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        query = 'protein=P0&filterM1=false&clusterRows=true&valueType=z'
        response = client.get('/api/plots/single-protein/phospho/heatmap.png?' + query + '&dpi=80')
        assert response.status_code == 200, response.text
        token = response.headers['X-CoPYlot-Notebook']
        url = '/api/plots/single-protein/phospho/heatmap-table?' + query + '&snapshot=' + token
        table = client.get(url)
        assert table.status_code == 200
        archive_url = f'/api/plots/notebooks/{token}.zip'
        archive = client.get(archive_url)
        assert archive.status_code == 200
        get_annotation('phospho').log2_data.loc[:, 'A1'] = 100.
        assert client.get(url).json() == table.json()
        assert client.get(archive_url).content == archive.content
        assert client.get(url.replace('valueType=z', 'valueType=log2')).status_code == 409
        owner = set_session_id('other-heatmap-owner')
        try:
            assert client.get(url).status_code == 404
            assert client.get(archive_url).status_code == 404
        finally:
            reset_session_id(owner)


@pytest.mark.parametrize('source', ['data', 'filtered', 'imputed'])
@pytest.mark.parametrize('identifier', ['workflow', 'genes'])
@pytest.mark.parametrize('show_na_low', [False, True])
def test_lineplot_exact_standalone_replay(inputs, tmp_path, source, identifier, show_na_low):
    from app.services.annotation_store import get_annotation
    # Multiple source rows per gene and a row mapping to both selected genes.
    for frame in [get_annotation('protein').source_data, get_annotation('protein').log2_data, get_annotation('protein').filtered_data]:
        frame.loc[0, 'GeneNames'] = 'G1;G2'
    options = dict(kind='protein', proteins=['G1', 'G2'] if identifier == 'genes' else ['P1', 'P2'],
        show_na_low=show_na_low,
        conditions=['B', 'A'], identifier=identifier, include_id=True, data_source=source, dpi=80,
        advanced={'titleElement': {'text': 'Selected features', 'size': 15, 'bold': True},
                  'xTickLabelRotation': 35, 'legendFontSize': 8})
    image, token = render_line(**options)
    assert image == single.single_protein_lineplot_plot(**options)
    recipe = snapshots.get(get_session_id(), token)
    preparation = {k: options[k] for k in ('kind', 'proteins', 'conditions', 'identifier', 'include_id', 'data_source')}
    pd.testing.assert_frame_equal(pd.read_parquet(io.BytesIO(recipe.resources['table.parquet'])),
                                  single.single_protein_lineplot_table(**preparation))
    assert recipe.uses_imputed_input == (source == 'imputed')
    _, blob = build_notebook_archive(recipe)
    with ZipFile(io.BytesIO(blob)) as archive:
        archive.extractall(tmp_path)
        name = next(n for n in archive.namelist() if n.endswith('.ipynb'))
    notebook = json.loads((tmp_path / name).read_text())
    cells = '\n'.join(''.join(c['source']) for c in notebook['cells'] if c['cell_type'] == 'code')
    cells = set_original_path(cells, tmp_path)
    run = subprocess.run([sys.executable, '-I', '-c', "import sys;sys.path.insert(0,'.');\n" + cells],
        cwd=tmp_path, capture_output=True, text=True, timeout=90)
    assert run.returncode == 0, run.stderr
    assert (tmp_path / 'reproduced.png').read_bytes() == image


@pytest.mark.parametrize('source', ['non_imputed', 'imputed'])
def test_lineplot_phosphosite_and_collapse(phosphosites, source):
    from app.services.phosprot_tools import aggregate_from_phospho
    aggregate_from_phospho('robust_site_median', source)
    for kind in ['phospho', 'phosprot']:
        frame, _, _ = single._analysis_frame(kind)
        key = single._line_box_key_column_for_identifier(kind, frame, 'workflow')
        options = dict(kind=kind, proteins=frame[key].astype(str).iloc[:2].tolist(), conditions=[], dpi=80, legend=False)
        image, token = render_line(**options)
        assert image == single.single_protein_lineplot_plot(**options)
        recipe = snapshots.get(get_session_id(), token)
        assert recipe.uses_imputed_input == (kind == 'phosprot' and source == 'imputed')


def test_line_snapshot_table_is_immutable_and_validates_selection(inputs):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes_plots import router
    from app.services.annotation_store import get_annotation
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get('/api/plots/single-protein/protein/lineplot.png?proteins=P1,P2&dpi=80&showNaLow=true')
        assert response.status_code == 200, response.text
        token = response.headers['X-CoPYlot-Notebook']
        assert snapshots.get(get_session_id(), token).settings['show_na_low'] is True
        url = f'/api/plots/single-protein/protein/lineplot-table?proteins=P1,P2&snapshot={token}'
        table = client.get(url)
        assert table.status_code == 200
        get_annotation('protein').log2_data.loc[:, 'A1'] = 100.
        assert client.get(url).json() == table.json()
        assert client.get(url + '&includeId=true').status_code == 409
        assert client.get(url.replace('proteins=P1,P2', 'proteins=P1')).status_code == 409


@pytest.mark.parametrize('source', ['data', 'filtered', 'imputed'])
@pytest.mark.parametrize('identifier', ['workflow', 'genes'])
def test_boxplot_exact_figure_table_and_isolated_replay(inputs, tmp_path, source, identifier):
    options = dict(kind='protein', protein='G1' if identifier == 'genes' else 'P1',
        identifier=identifier, conditions=['A', 'B'], data_source=source, dpi=80,
        dots=True, outliers=True, sample_n=False, random_seed=17,
        advanced={'conditionLabels': {'A': 'Treatment'}, 'boxMedianColor': '#ab1234',
                  'xTickLabelRotation': 30})
    expected = single.single_protein_boxplot_plot(**options)
    actual, token = render_box(**options)
    assert actual == expected
    recipe = snapshots.get(get_session_id(), token)
    preparation = {k: options[k] for k in ('kind', 'protein', 'conditions', 'identifier', 'data_source')}
    pd.testing.assert_frame_equal(pd.read_parquet(io.BytesIO(recipe.resources['table.parquet'])),
                                  single.single_protein_boxplot_table(**preparation))
    assert recipe.uses_imputed_input == (source == 'imputed')
    if source == 'imputed':
        assert 'seed=77' in recipe.imputation_recipe
    _, blob = build_notebook_archive(recipe)
    with ZipFile(io.BytesIO(blob)) as archive:
        archive.extractall(tmp_path)
        name = next(n for n in archive.namelist() if n.endswith('.ipynb'))
    notebook = json.loads((tmp_path / name).read_text())
    cells = '\n'.join(''.join(c['source']) for c in notebook['cells'] if c['cell_type'] == 'code')
    cells = set_original_path(cells, tmp_path)
    run = subprocess.run([sys.executable, '-I', '-c', "import sys;sys.path.insert(0,'.');\n" + cells],
        cwd=tmp_path, capture_output=True, text=True, timeout=90)
    assert run.returncode == 0, run.stderr
    assert (tmp_path / 'reproduced.png').read_bytes() == actual
    assert (tmp_path / 'reproduced_summary.csv').exists()


@pytest.mark.parametrize('source', ['non_imputed', 'imputed'])
def test_phosphosite_and_collapsed_boxplots_preserve_history(phosphosites, source):
    from app.services.phosprot_tools import aggregate_from_phospho
    aggregate_from_phospho('robust_site_median', source)
    for kind in ['phospho', 'phosprot']:
        frame, _, _ = single._analysis_frame(kind)
        key = single._line_box_key_column_for_identifier(kind, frame, 'workflow')
        options = dict(kind=kind, protein=str(frame[key].iloc[0]), conditions=[], dpi=80)
        image, token = render_box(**options)
        assert image == single.single_protein_boxplot_plot(**options)
        recipe = snapshots.get(get_session_id(), token)
        assert recipe.uses_imputed_input == (kind == 'phosprot' and source == 'imputed')
        build_notebook_archive(recipe)


def test_gene_consolidation_and_empty_values(inputs):
    from app.services.annotation_store import get_annotation
    frame = get_annotation('protein').log2_data
    frame.loc[:2, 'GeneNames'] = 'COMMON;SECOND'
    for conditions in [['A', 'B'], ['C']]:
        if conditions == ['C']:
            frame.loc[:2, ['C1', 'C2', 'C3', 'C4']] = float('nan')
        get_annotation('protein').source_data = frame.copy()
        options = dict(kind='protein', protein='common', identifier='genes', conditions=conditions, dpi=80)
        image, token = render_box(**options)
        assert image == single.single_protein_boxplot_plot(**options)
        recipe = snapshots.get(get_session_id(), token)
        table = pd.read_parquet(io.BytesIO(recipe.resources['table.parquet']))
        pd.testing.assert_frame_equal(table, single.single_protein_boxplot_table(**{k: v for k, v in options.items() if k != 'dpi'}))
        if not table.empty:
            assert table.SourceFeatureCount.tolist() == [3, 3]


def test_boxplot_snapshot_is_frozen_owned_and_matches_settings(inputs, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes_plots import router
    from app.services.annotation_store import get_annotation
    from app.services.session_context import set_session_id, reset_session_id
    monkeypatch.setenv('COPYLOT_SESSION_ISOLATION', '1')
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get('/api/plots/single-protein/protein/boxplot.png?protein=P1&dpi=80')
        assert response.status_code == 200, response.text
        token = response.headers['X-CoPYlot-Notebook']
        url = f'/api/plots/single-protein/protein/boxplot-table?protein=P1&snapshot={token}'
        table = client.get(url)
        assert table.status_code == 200
        archive = f'/api/plots/notebooks/{token}.zip'
        original = client.get(archive)
        assert original.status_code == 200
        get_annotation('protein').log2_data.loc[:, 'A1'] = 100.
        assert client.get(url).json() == table.json()
        assert client.get(archive).content == original.content
        assert client.get(url.replace('protein=P1', 'protein=P2')).status_code == 409
        owner = set_session_id('other-box-owner')
        try:
            assert client.get(url).status_code == 404
            assert client.get(archive).status_code == 404
        finally:
            reset_session_id(owner)


@pytest.mark.parametrize('plot', ['boxplot', 'lineplot'])
def test_missing_history_keeps_plot_available(phosphosites, plot):
    from app.services.phosprot_tools import aggregate_from_phospho
    from app.services.annotation_store import get_annotation
    from app.api import routes_plots
    aggregate_from_phospho('mean', 'non_imputed')
    annotation = get_annotation('phosprot')
    key = single._line_box_key_column_for_identifier('phosprot', annotation.log2_data, 'workflow')
    protein = str(annotation.log2_data[key].iloc[0])
    annotation.phosprot_lineage = None
    route = getattr(routes_plots, f'single_protein_{plot}_route')
    renderer = getattr(single, f'single_protein_{plot}_plot')
    response = route(kind='phosprot', dpi=80, **({'protein': protein} if plot == 'boxplot' else {'proteins': protein}))
    options = {'protein': protein} if plot == 'boxplot' else {'proteins': [protein]}
    assert response.body == renderer(kind='phosprot', conditions=[], dpi=80, **options)
    assert 'X-CoPYlot-Notebook' not in response.headers
    assert 'X-CoPYlot-Notice' in response.headers


@pytest.mark.parametrize('plot', ['boxplot', 'lineplot'])
def test_concurrent_change_does_not_publish_snapshot(inputs, monkeypatch, plot):
    from app.services import runtime_cache
    revisions = iter([1, 2])
    monkeypatch.setattr(runtime_cache, 'runtime_cache_version', lambda: next(revisions))
    renderer = render_box if plot == 'boxplot' else render_line
    options = {'protein': 'P1'} if plot == 'boxplot' else {'proteins': ['P1']}
    image, token = renderer(kind='protein', conditions=[], dpi=80, **options)
    assert image.startswith(b'\x89PNG')
    assert token == ''
