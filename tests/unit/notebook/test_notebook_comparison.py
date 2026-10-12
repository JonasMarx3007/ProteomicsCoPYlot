from notebook_replay_support import set_original_path

import io
import json
import subprocess
import sys
from zipfile import ZipFile

import pandas as pd
import pytest

from app.services.notebook_comparison import render_comparison, comparison_module
from app.services.notebook_archive import build_notebook_archive
from app.services.notebook_snapshots import snapshots
from app.services.session_context import get_session_id


@pytest.mark.parametrize('mode', ['Single', 'Condition'])
@pytest.mark.parametrize('plot,interactive', [('pearson', False), ('pearson', True), ('venn', False)])
def test_comparison_notebook_replays(phosphosites, tmp_path, monkeypatch, mode, plot, interactive):
    from app.services import comparison_tools
    options = dict(kind='phospho', mode=mode, alias1='Left sample', alias2='Right sample',
        advanced={'titleElement': {'size': 14, 'bold': True}, 'markerSize': 5,
                  'vennColor1': '#8899aa', 'conditionLabels': {'B': 'Treatment'}})
    if plot == 'pearson':
        options.update(sample1='A1', sample2='B1', condition1='A', condition2='B')
    else:
        options.update(first='A1' if mode == 'Single' else 'A',
            second='B1' if mode == 'Single' else 'B', third='B2' if mode == 'Single' else '')
    if not interactive:
        options['dpi'] = 80
    content, token = render_comparison(plot, interactive=interactive, **options)
    recipe = snapshots.get(get_session_id(), token)
    prefix = 'pearson_correlation' if plot == 'pearson' else 'venn'
    table_options = {k: v for k, v in options.items() if k not in {'advanced', 'dpi'}}
    table = getattr(comparison_tools, prefix + '_table')(**table_options)
    pd.testing.assert_frame_equal(table, pd.DataFrame(json.loads(recipe.resources['table.json'])))
    assert not recipe.uses_imputed_input
    assert 'UPD_seq' not in pd.read_parquet(io.BytesIO(recipe.resources['input.parquet']))
    if interactive:
        monkeypatch.setattr(comparison_tools, '_plotly_html', comparison_module(plot, True).plotly_html)
    expected = getattr(comparison_tools, prefix + ('_html' if interactive else '_png'))(**options)
    assert content == expected
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
    assert (tmp_path / ('reproduced.html' if interactive else 'reproduced.png')).read_bytes() == (
        content.encode() if interactive else content)


def test_comparison_snapshot_routes(phosphosites, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes_plots import router
    from app.services.session_context import set_session_id, reset_session_id
    monkeypatch.setenv('COPYLOT_SESSION_ISOLATION', '1')
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        for plot, query in [('pearson', '?sample1=A1&sample2=B1'), ('venn', '?first=A1&second=B1')]:
            base = '/api/plots/comparison/phospho/' + plot
            response = client.get(base + '.png' + query + '&dpi=80')
            assert response.status_code == 200, response.text
            token = response.headers['X-CoPYlot-Notebook']
            url = base + '-table' + query + '&snapshot=' + token
            assert client.get(url).json() == client.get(base + '-table' + query).json()
            assert client.get(url + '&alias1=changed').status_code == 409
            owner = set_session_id('other-comparison-owner')
            try:
                assert client.get(url).status_code == 404
            finally:
                reset_session_id(owner)


@pytest.mark.parametrize('kind', ['protein', 'phosprot'])
def test_comparison_levels_and_upstream_imputation(phosphosites, kind):
    from app.services.annotation_store import get_annotation, save_annotation
    from app.services.dataset_store import save_table_dataset
    from app.services.phosprot_tools import aggregate_from_phospho
    from app.services import comparison_tools
    from app.schemas.annotation import AnnotationGenerateRequest
    from app.api.routes_annotations import generate_annotation
    annotation = get_annotation('phospho')
    if kind == 'protein':
        frame = annotation.log2_data.rename(columns={'Protein_group': 'ProteinNames'})
        save_table_dataset('proteins.csv', kind, frame)
        save_annotation(kind=kind, source_data=frame, log2_data=frame, filtered_data=frame.iloc[:1],
            metadata=annotation.metadata, is_log2_transformed=True, metadata_source='manual',
            filter_config=annotation.filter_config, auto_detected=False, warnings=[])
    else:
        aggregate_from_phospho(source='imputed', mode='mean')
        generate_annotation(AnnotationGenerateRequest(kind='phosprot', isLog2Transformed=True,
            conditions=[{'name': group, 'columns': [f'{group}{i}' for i in range(1, 5)]} for group in 'AB']))
    for plot in ('pearson', 'venn'):
        options = dict(kind=kind, sample1='A1', sample2='B1') if plot == 'pearson' else dict(kind=kind, first='A1', second='B1')
        content, token = render_comparison(plot, dpi=80, **options)
        recipe = snapshots.get(get_session_id(), token)
        assert recipe.uses_imputed_input == (kind == 'phosprot')
        if kind == 'phosprot':
            assert recipe.provenance['upstreamCollapse']['source'] == 'imputed'
            assert 'BEFORE' in recipe.imputation_recipe
        original = comparison_tools.pearson_correlation_png if plot == 'pearson' else comparison_tools.venn_png
        assert content == original(dpi=80, **options)


def test_comparison_missing_pairs_and_duplicate_identifiers():
    data = pd.DataFrame({'ProteinNames': ['P1', 'P1', 'P2'],
        'A': [0.0, None, None], 'B': [1.0, 2.0, None], 'C': [None, None, None]})
    metadata = pd.DataFrame({'sample': ['A', 'B', 'C'], 'condition': ['A', 'B', 'C']})
    pearson = comparison_module('pearson')
    summary = pearson.prepare_table(data, metadata, kind='protein', sample1='A', sample2='B')
    assert summary.Value.tolist() == ['A', 'B', 1, '']
    assert pearson.render_plot(data, metadata, kind='protein', sample1='A', sample2='B', dpi=80)
    with pytest.raises(ValueError, match='No overlapping'):
        pearson.render_plot(data, metadata, kind='protein', sample1='A', sample2='C')
    venn = comparison_module('venn')
    table = venn.prepare_table(data, metadata, kind='protein', first='A', second='B', third='C')
    assert table.Count.tolist() == [0, 0, 0, 1, 0, 0, 0, 1, 1, 0]
