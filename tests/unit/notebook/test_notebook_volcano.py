from notebook_replay_support import set_original_path

import io
import json
import subprocess
import sys
from zipfile import ZipFile

import pandas as pd
import pytest

from app.schemas.stats import VolcanoRequest, VolcanoControlRequest
from app.services import stats_tools
from app.services.notebook_archive import build_notebook_archive
from app.services.notebook_volcano import render_volcano
from app.services.notebook_snapshots import snapshots
from app.services.session_context import get_session_id


@pytest.mark.parametrize('test_type', ['unpaired', 'unpaired_welch', 'paired'])
@pytest.mark.parametrize('control,source', [(False, 'data'), (False, 'imputed'), (True, 'filtered')])
def test_volcano_statistics_and_standalone_plot_match_app(inputs, tmp_path, test_type, control, source):
    cls = VolcanoControlRequest if control else VolcanoRequest
    extra = dict(condition1Control='C', condition2Control='D') if control else {}
    payload = cls(kind='protein', condition1='A', condition2='B', dataSource=source,
                  testType=test_type, identifier='genes', highlightTerms=['G3'],
                  useUncorrected=test_type == 'unpaired_welch', **extra)
    options = dict(dpi=80, label_top_up=2, label_top_down=2,
                   advanced={'volcanoNsColor': '#8899aa', 'conditionLabels': {'A': 'Treatment'}})
    expected = stats_tools.volcano_png(payload, **options)
    actual, token = render_volcano(payload, **options)
    assert actual == expected
    recipe = snapshots.get(get_session_id(), token)
    expected_table, _ = stats_tools._volcano_inputs(payload)
    pd.testing.assert_frame_equal(pd.read_parquet(io.BytesIO(recipe.resources['table.parquet'])), expected_table)
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


def test_volcano_snapshot_route_is_frozen_and_owned(inputs, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes_plots import router
    from app.services.annotation_store import get_annotation
    from app.services.session_context import set_session_id, reset_session_id
    monkeypatch.setenv('COPYLOT_SESSION_ISOLATION', '1')
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        image = client.get('/api/plots/stats/protein/volcano.png?condition1=A&condition2=B&dpi=80')
        assert image.status_code == 200, image.text
        token = image.headers['X-CoPYlot-Notebook']
        url = f'/api/plots/stats/protein/volcano-table?snapshot={token}'
        response = client.get(url)
        assert response.status_code == 200
        expected = stats_tools.run_volcano(VolcanoRequest(kind='protein', condition1='A', condition2='B')).model_dump()
        assert response.json() == expected
        get_annotation('protein').log2_data.loc[:, 'A1'] = 100.
        assert client.get(url).json() == expected
        assert client.get(url.replace('/protein/', '/phospho/')).status_code == 409
        assert client.get(f'/api/plots/notebooks/{token}.zip').status_code == 200
        other = set_session_id('another-owner')
        try:
            assert client.get(url).status_code == 404
        finally:
            reset_session_id(other)


@pytest.mark.parametrize('source', ['non_imputed', 'imputed'])
def test_phosphoprotein_counts_and_imputation_history(phosphosites, source):
    from app.services.phosprot_tools import aggregate_from_phospho
    aggregate_from_phospho('robust_site_median', source)
    for kind in ['phospho', 'phosprot']:
        payload = VolcanoRequest(kind=kind, condition1='A', condition2='B')
        actual, token = render_volcano(payload, dpi=80)
        assert actual == stats_tools.volcano_png(payload, dpi=80)
        recipe = snapshots.get(get_session_id(), token)
        expected, _ = stats_tools._volcano_inputs(payload)
        pd.testing.assert_frame_equal(pd.read_parquet(io.BytesIO(recipe.resources['table.parquet'])), expected)
        assert recipe.uses_imputed_input == (kind == 'phosprot' and source == 'imputed')
        build_notebook_archive(recipe)


def test_unknown_collapse_history_does_not_break_the_plot(phosphosites):
    from app.services.phosprot_tools import aggregate_from_phospho
    from app.services.annotation_store import get_annotation
    from app.api.plots_stats import _volcano_notebook_png
    aggregate_from_phospho('mean', 'non_imputed')
    get_annotation('phosprot').phosprot_lineage = None
    payload = VolcanoRequest(kind='phosprot', condition1='A', condition2='B')
    response = _volcano_notebook_png(payload, dpi=80)
    assert response.body == stats_tools.volcano_png(payload, dpi=80)
    assert 'X-CoPYlot-Notebook' not in response.headers


def test_concurrent_edits_do_not_publish_a_mixed_snapshot(inputs, monkeypatch):
    from app.services import runtime_cache
    revisions = iter([1, 2])
    monkeypatch.setattr(runtime_cache, 'runtime_cache_version', lambda: next(revisions))
    content, token = render_volcano(VolcanoRequest(kind='protein', condition1='A', condition2='B'), dpi=80)
    assert content.startswith(b'\x89PNG')
    assert token == ''


@pytest.mark.parametrize('control,source,test_type', [
    (False, 'data', 'unpaired'), (False, 'imputed', 'paired'),
    (True, 'filtered', 'unpaired_welch'), (True, 'imputed', 'paired'),
])
def test_interactive_volcano_matches_traces_and_replays_offline(inputs, tmp_path, control, source, test_type):
    from app.services.plot_styling import advanced_plotly_layout
    cls = VolcanoControlRequest if control else VolcanoRequest
    extra = dict(condition1Control='C', condition2Control='D') if control else {}
    payload = cls(kind='protein', condition1='A', condition2='B', dataSource=source,
                  testType=test_type, highlightTerms=['P3'], **extra)
    advanced = {'volcanoNsColor': '#887766', 'markerShape': 'diamond',
                'conditionLabels': {'A': 'Treatment'}, 'xTickLabelRotation': 30}
    table, arguments = stats_tools._volcano_inputs(payload)
    expected = stats_tools._volcano_figure(table, **arguments, advanced=advanced)
    expected.update_layout(**advanced_plotly_layout(advanced))
    html, token = render_volcano(payload, interactive=True, advanced=advanced)
    recipe = snapshots.get(get_session_id(), token)
    assert json.loads(recipe.resources['figure.json']) == json.loads(expected.to_json())
    assert 'copylot-plot-ready' in html
    assert recipe.provenance['view'] == 'interactive'
    assert '_volcano_png_figure' not in recipe.source.functions
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
    assert (tmp_path / 'reproduced.html').read_text(encoding='utf-8') == html


@pytest.mark.parametrize('source', ['non_imputed', 'imputed'])
def test_interactive_phospho_and_phosprot_preserve_results(phosphosites, source):
    from app.services.phosprot_tools import aggregate_from_phospho
    aggregate_from_phospho('robust_site_median', source)
    for kind in ['phospho', 'phosprot']:
        payload = VolcanoRequest(kind=kind, condition1='A', condition2='B')
        _, token = render_volcano(payload, interactive=True)
        recipe = snapshots.get(get_session_id(), token)
        table, arguments = stats_tools._volcano_inputs(payload)
        figure = stats_tools._volcano_figure(table, **arguments)
        figure.update_layout(**stats_tools.advanced_plotly_layout(None))
        assert json.loads(recipe.resources['figure.json']) == json.loads(figure.to_json())
        assert recipe.uses_imputed_input == (kind == 'phosprot' and source == 'imputed')


@pytest.mark.parametrize('control', [False, True])
def test_interactive_routes_pair_the_frozen_table(inputs, control):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes_plots import router
    app = FastAPI()
    app.include_router(router)
    name = 'volcano-control' if control else 'volcano'
    controls = '&condition1Control=C&condition2Control=D' if control else ''
    with TestClient(app) as client:
        response = client.get(f'/api/plots/stats/protein/{name}.html?condition1=A&condition2=B{controls}')
        assert response.status_code == 200, response.text
        token = response.headers['X-CoPYlot-Notebook']
        recipe = snapshots.get(get_session_id(), token)
        table = client.get(f'/api/plots/stats/protein/volcano-table?snapshot={token}')
        assert table.status_code == 200
        assert table.json()['totalRows'] == len(pd.read_parquet(io.BytesIO(recipe.resources['table.parquet'])))
        assert client.get(f'/api/plots/notebooks/{token}.zip').status_code == 200
