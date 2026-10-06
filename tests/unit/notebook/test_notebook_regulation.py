from notebook_replay_support import set_original_path

import io
import json
import subprocess
import sys
from zipfile import ZipFile

import pandas as pd
import pytest

from app.services.notebook_regulation import render_regulation
from app.services.notebook_archive import build_notebook_archive
from app.services.notebook_qc import snapshots
from app.services.session_context import get_session_id
from test_notebook_phosprot import phosphosites


@pytest.mark.parametrize('source', ['data', 'filtered', 'imputed'])
@pytest.mark.parametrize('interactive', [False, True])
def test_regulation_replays(phosphosites, tmp_path, monkeypatch, source, interactive):
    from app.services.phospho_tools import phosprot_regulation_table, phosprot_regulation_png
    from app.services.annotation_store import get_annotation
    get_annotation('phospho').metadata['pair_id'] = ['1', '2', '3', '4'] * 2
    options = dict(condition1='A', condition2='B', data_source=source,
        test_type='paired' if source == 'filtered' else 'unpaired_welch',
        p_value_threshold=1, log2fc_threshold=0, max_hover_sites=1,
        show_phosphosites=source != 'filtered')
    advanced = {'titleElement': {'size': 15, 'bold': True}, 'markerSize': 7}
    content, token = render_regulation(interactive=interactive, advanced=advanced, **options)
    recipe = snapshots.get(get_session_id(), token)
    table = pd.read_parquet(io.BytesIO(recipe.resources['table.parquet']))
    pd.testing.assert_frame_equal(table, phosprot_regulation_table(**options))
    assert not table.empty
    assert recipe.uses_imputed_input == (source == 'imputed')
    if not interactive:
        assert content == phosprot_regulation_png(advanced=advanced, **options)
    else:
        from app.services import phospho_tools
        from app.services.notebook_regulation import regulation_module
        monkeypatch.setattr(phospho_tools, '_plotly_html', regulation_module(True).plotly_html)
        assert content == phospho_tools.phosprot_regulation_html(advanced=advanced, **options)
        assert 'copylot-plot-ready' in content
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
    output = (tmp_path / ('reproduced.html' if interactive else 'reproduced.png')).read_bytes()
    assert output == (content.encode() if interactive else content)


@pytest.mark.parametrize('interactive', [False, True])
def test_empty_regulation(phosphosites, interactive):
    from app.services.phospho_tools import phosprot_regulation_table
    options = dict(condition1='A', condition2='B', log2fc_threshold=100)
    content, token = render_regulation(interactive=interactive, **options)
    recipe = snapshots.get(get_session_id(), token)
    table = pd.read_parquet(io.BytesIO(recipe.resources['table.parquet']))
    assert table.empty and content
    pd.testing.assert_frame_equal(table, phosprot_regulation_table(**options))


def test_regulation_route_snapshot_settings_and_owner(phosphosites, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes_plots import router
    from app.services.session_context import set_session_id, reset_session_id
    monkeypatch.setenv('COPYLOT_SESSION_ISOLATION', '1')
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        query = '?condition1=A&condition2=B'
        response = client.get('/api/plots/phospho/phosprot-regulation.html' + query)
        assert response.status_code == 200, response.text
        token = response.headers['X-CoPYlot-Notebook']
        url = '/api/plots/phospho/phosprot-regulation-table' + query + '&snapshot=' + token
        assert client.get(url).status_code == 200
        assert client.get(url + '&maxHoverSites=1').status_code == 409
        owner = set_session_id('other-regulation-owner')
        try:
            assert client.get(url).status_code == 404
        finally:
            reset_session_id(owner)
