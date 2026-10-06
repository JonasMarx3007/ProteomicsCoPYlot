from notebook_replay_support import set_original_path

import io
import json
import subprocess
import sys
from zipfile import ZipFile

import pandas as pd
import pytest

from app.services.notebook_ksea import capture_table
from app.services.notebook_archive import build_notebook_archive
from app.services.notebook_qc import snapshots
from app.services.session_context import get_session_id
from test_notebook_phosprot import phosphosites


@pytest.mark.parametrize('source', ['data', 'filtered', 'imputed'])
@pytest.mark.parametrize('control', [False, True])
def test_table_only_notebook_replays(phosphosites, tmp_path, monkeypatch, source, control):
    from app.services.annotation_store import get_annotation
    from app.services.phospho_tools import ksea_table
    annotation = get_annotation('phospho')
    annotation.metadata['pair_id'] = ['1', '2', '3', '4'] * 2
    if not control:
        from app.services import phospho_tools
        monkeypatch.setattr(phospho_tools, '_ksea_protein_sequences', lambda organism:
            {'P00001': 'AAAAAAASAAAAAAA', 'UNUSED': 'UNUSED'})
        for frame in (annotation.source_data, annotation.log2_data, annotation.filtered_data, annotation.imputed_data):
            frame['PTM_Collapse_key'] = 'P00001~GENE_S8_M1'
            frame['UPD_seq'] = 'AAAAAAASAAAAAAA'
    if control:
        annotation.metadata['condition'] = ['A', 'A', 'B', 'B', 'C', 'C', 'D', 'D']
    options = dict(condition1='A', condition2='B', organism='none' if control else 'human', data_source=source,
                   test_type='paired' if not control and source == 'filtered' else 'unpaired_welch',
                   source='volcano_control' if control else 'volcano',
                   **({'condition1_control': 'C', 'condition2_control': 'D'} if control else {}))
    table, token = capture_table(**options)
    pd.testing.assert_frame_equal(table, ksea_table(**options))
    recipe = snapshots.get(get_session_id(), token)
    assert recipe.uses_imputed_input == (source == 'imputed')
    assert not any('plot' in name for name in recipe.source.functions)
    if not control:
        assert json.loads(recipe.resources['sequences.json']) == {'P00001': 'AAAAAAASAAAAAAA'}
        assert set(table.window_source) == {'protein'}
    _, blob = build_notebook_archive(recipe)
    with ZipFile(io.BytesIO(blob)) as archive:
        assert not any(name.endswith(('.png', '.html')) for name in archive.namelist())
        archive.extractall(tmp_path)
        name = next(n for n in archive.namelist() if n.endswith('.ipynb'))
    notebook = json.loads((tmp_path / name).read_text())
    cells = '\n'.join(''.join(c['source']) for c in notebook['cells'] if c['cell_type'] == 'code')
    cells = set_original_path(cells, tmp_path)
    run = subprocess.run([sys.executable, '-I', '-c', "import sys;sys.path.insert(0,'.');\n" + cells],
        cwd=tmp_path, capture_output=True, text=True, timeout=90)
    assert run.returncode == 0, run.stderr
    assert (tmp_path / 'KinaseLibrary_input.tsv').read_text() == table.to_csv(sep='\t', index=False, lineterminator='\n')


def test_table_route_token_owned(phosphosites, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes_plots import router
    from app.services.session_context import set_session_id, reset_session_id
    monkeypatch.setenv('COPYLOT_SESSION_ISOLATION', '1')
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get('/api/plots/phospho/ksea-table?condition1=A&condition2=B&organism=none')
        assert response.status_code == 200, response.text
        url = '/api/plots/notebooks/' + response.json()['notebookToken'] + '.zip'
        assert client.get(url).status_code == 200
        owner = set_session_id('other-ksea-owner')
        try:
            assert client.get(url).status_code == 404
        finally:
            reset_session_id(owner)


def test_a_table_identified_only_by_peptide_sequence_still_gets_its_table(phosphosites):
    """A phosphosite table without PTM_Collapse_key is supported by the app; the
    notebook preparation used to raise a KeyError there and take the table down with it."""
    from app.services.annotation_store import get_annotation
    from app.services.phospho_tools import ksea_table
    annotation = get_annotation('phospho')
    for name in ('source_data', 'log2_data', 'filtered_data', 'imputed_data'):
        setattr(annotation, name, getattr(annotation, name).drop(columns=['PTM_Collapse_key']))
    options = dict(condition1='A', condition2='B', organism='human', data_source='data')
    table, _ = capture_table(**options)
    pd.testing.assert_frame_equal(table, ksea_table(**options))
