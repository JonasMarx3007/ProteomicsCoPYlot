from notebook_replay_support import set_original_path

import io
import json
import subprocess
import sys
from zipfile import ZipFile

import pandas as pd
import pytest

from app.services import phospho_tools
from app.services.notebook_phospho import render_counts, count_module, render_coverage
from app.services.notebook_archive import build_notebook_archive
from app.services.notebook_qc import snapshots
from app.services.session_context import get_session_id
from test_notebook_phosprot import phosphosites


@pytest.mark.parametrize('plot,site_num,trim', [('distribution', False, 0), ('distribution', False, .25),
    ('distribution', True, .25), ('sty', False, 0)])
def test_distribution_and_sty_standalone(phosphosites, tmp_path, plot, site_num, trim):
    from app.services.annotation_store import get_annotation
    from app.services.notebook_phospho import render_distribution, render_sty
    frame = get_annotation('phospho').source_data
    frame['PTM_Collapse_key'] = ['P~G_S1_M1', 'P_T2_M1', 'P_Y3_M1', 'unknown'] * 3
    frame['Protein_group'] = ['P1'] * 5 + ['P2'] * 3 + ['P3'] * 4
    if site_num:
        frame['site_num'] = [1, 2, 3, 4, 10, 10, 2, 3, 3, 1, 1, 1]
    renderer = render_distribution if plot == 'distribution' else render_sty
    options = dict(dpi=80, advanced={'titleElement': {'text': 'Captured result', 'bold': True},
                                   'xTickLabelRotation': 25})
    if plot == 'distribution':
        options['cutoff'] = trim
    image, token = renderer(**options)
    assert image == getattr(phospho_tools, f'phospho_{plot}_png')(**options)
    recipe = snapshots.get(get_session_id(), token)
    table = pd.read_parquet(io.BytesIO(recipe.resources['table.parquet']))
    pd.testing.assert_frame_equal(table, getattr(phospho_tools, f'phospho_{plot}_table')(
        **({'cutoff': trim} if plot == 'distribution' else {})))
    if plot == 'sty':
        assert table.Count.tolist() == [3, 3, 3, 3]
        assert table.Percentage.tolist() == [25.] * 4
    assert not recipe.uses_imputed_input
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


@pytest.mark.parametrize('plot', ['distribution', 'sty'])
def test_category_snapshot_tables(phosphosites, plot):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes_plots import router
    from app.services.annotation_store import get_annotation
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        image = client.get(f'/api/plots/phospho/{plot}.png?dpi=80')
        assert image.status_code == 200, image.text
        token = image.headers['X-CoPYlot-Notebook']
        url = f'/api/plots/phospho/{plot}-table?snapshot={token}'
        table = client.get(url)
        assert table.status_code == 200
        get_annotation('phospho').source_data['PTM_Collapse_key'] = 'changed'
        assert client.get(url).json() == table.json()
        other = 'sty' if plot == 'distribution' else 'distribution'
        assert client.get(url.replace(f'/{plot}-table', f'/{other}-table')).status_code == 409
        if plot == 'distribution':
            assert client.get(url + '&cutoff=0.2').status_code == 409


@pytest.mark.parametrize('mode', ['Normal', 'Summary'])
@pytest.mark.parametrize('log2', [False, True])
def test_coverage_exact_standalone_and_scale(phosphosites, tmp_path, mode, log2):
    from app.services.annotation_store import get_annotation
    annotation = get_annotation('phospho')
    annotation.is_log2_transformed = log2
    frame = annotation.source_data
    frame['PTM_localization'] = [.75, .5, None, 1.2] * 3
    frame.loc[0, 'A1'] = 0.
    frame.loc[1, 'A2'] = float('inf')
    options = dict(mode=mode, conditions=['B', 'A'], include_id=True, dpi=80, random_seed=33,
        advanced={'classIColor': '#112233', 'conditionLabels': {'A': 'Treatment'}, 'legendFontSize': 8})
    image, token = render_coverage(**options)
    assert image == phospho_tools.phospho_coverage_png(**options)
    recipe = snapshots.get(get_session_id(), token)
    table = pd.read_parquet(io.BytesIO(recipe.resources['table.parquet']))
    pd.testing.assert_frame_equal(table, phospho_tools.phospho_coverage_table(
        mode=mode, conditions=['B', 'A'], include_id=True))
    assert not recipe.uses_imputed_input
    if mode == 'Normal':
        assert table.iloc[0]['Class I'] == (3 if log2 else 2)
        assert table.iloc[0]['Unclassified'] == 6
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


def test_coverage_snapshot_rejects_mismatched_table(phosphosites):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes_plots import router
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        image = client.get('/api/plots/phospho/coverage.png?mode=Summary&conditions=A&dpi=80')
        assert image.status_code == 200, image.text
        token = image.headers['X-CoPYlot-Notebook']
        url = '/api/plots/phospho/coverage-table?mode=Summary&conditions=A&snapshot=' + token
        assert client.get(url).status_code == 200
        assert client.get(url.replace('conditions=A', 'conditions=B')).status_code == 409
        assert client.get(url.replace('mode=Summary', 'mode=Normal')).status_code == 409


@pytest.mark.parametrize('cutoff', [0, .75])
def test_counts_exact_and_standalone(phosphosites, tmp_path, cutoff):
    from app.services.annotation_store import get_annotation
    from app.services.phospho_localization import set_localization_cutoff
    frame = get_annotation('phospho').source_data
    frame['PTM_localization'] = [.5, .9, 1.] * 4
    frame['PrivatePath'] = r'C:\private_input\file.tsv'
    set_localization_cutoff(cutoff)
    options = dict(dpi=80, color='#112233', advanced={'barColor': '#aa2244',
        'titleElement': {'text': 'Site counts', 'bold': True}})
    image, token = render_counts(**options)
    assert image == phospho_tools.phosphosite_plot_png(**options)
    recipe = snapshots.get(get_session_id(), token)
    table = pd.read_parquet(io.BytesIO(recipe.resources['table.parquet']))
    pd.testing.assert_frame_equal(table, phospho_tools.phosphosite_plot_table())
    assert recipe.provenance['localizationCutoff'] == cutoff
    assert not recipe.uses_imputed_input
    assert len(pd.read_parquet(io.BytesIO(recipe.resources['input.parquet']))) == (12 if cutoff == 0 else 8)
    _, blob = build_notebook_archive(recipe)
    with ZipFile(io.BytesIO(blob)) as archive:
        assert all(b'private_input' not in archive.read(n) for n in archive.namelist())
        archive.extractall(tmp_path)
        name = next(n for n in archive.namelist() if n.endswith('.ipynb'))
    notebook = json.loads((tmp_path / name).read_text())
    cells = '\n'.join(''.join(c['source']) for c in notebook['cells'] if c['cell_type'] == 'code')
    cells = set_original_path(cells, tmp_path)
    run = subprocess.run([sys.executable, '-I', '-c', "import sys;sys.path.insert(0,'.');\n" + cells],
        cwd=tmp_path, capture_output=True, text=True, timeout=90)
    assert run.returncode == 0, run.stderr
    assert (tmp_path / 'reproduced.png').read_bytes() == image


@pytest.mark.parametrize('columns', [[], ['PTM_Collapse_key'], ['Phosphoprotein', 'PTM_Collapse_key'],
    ['Protein_group', 'UPD_seq', 'PTM_Collapse_key']])
def test_count_column_fallbacks_match_original(monkeypatch, columns):
    frame = pd.DataFrame({'Protein_group': ['P1', 'P1', 'P2'], 'Phosphoprotein': ['P1', 'P1', 'P2'],
        'UPD_seq': ['ab-c', 'ABC', 'DEF'], 'PTM_Collapse_key': ['S1', 'S1', 'S2']})[columns]
    monkeypatch.setattr(phospho_tools, '_phospho_context', lambda: (frame, pd.DataFrame(), []))
    pd.testing.assert_frame_equal(count_module().prepare_table(frame), phospho_tools.phosphosite_plot_table())


def test_count_snapshot_is_frozen_and_owned(phosphosites, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes_plots import router
    from app.services.annotation_store import get_annotation
    from app.services.session_context import set_session_id, reset_session_id
    monkeypatch.setenv('COPYLOT_SESSION_ISOLATION', '1')
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get('/api/plots/phospho/phosphosite-plot.png?dpi=80')
        assert response.status_code == 200, response.text
        token = response.headers['X-CoPYlot-Notebook']
        url = '/api/plots/phospho/phosphosite-plot-table?snapshot=' + token
        table = client.get(url)
        assert table.status_code == 200
        archive_url = f'/api/plots/notebooks/{token}.zip'
        archive = client.get(archive_url)
        assert archive.status_code == 200
        get_annotation('phospho').source_data['PTM_Collapse_key'] = 'changed'
        assert client.get(url).json() == table.json()
        assert client.get(archive_url).content == archive.content
        owner = set_session_id('other-count-owner')
        try:
            assert client.get(url).status_code == 404
            assert client.get(archive_url).status_code == 404
        finally:
            reset_session_id(owner)
