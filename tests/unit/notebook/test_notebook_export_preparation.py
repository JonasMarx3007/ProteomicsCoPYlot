"""When a figure's notebook is prepared, and what the page is told when it cannot be.

A render used to replay the whole recorded preprocessing -- for VSN data a fit
in R -- on every plot, whether or not anyone exported it. A render now only
binds what the replay needs; the replay runs, and is checked, on download. A
render that can offer no notebook says why under the plot, and a download that
cannot be prepared says what stands in the way.
"""
from __future__ import annotations

import json
from urllib.parse import unquote

import pytest

from app.services import notebook_preprocessing
from app.services.notebook_qc import snapshots
from app.services.notebook_snapshots import PendingRecipe
from app.services.session_context import get_session_id


def test_a_render_binds_the_replay_and_the_download_runs_it(client, monkeypatch):
    calls = []
    original = notebook_preprocessing.preprocessing_source
    monkeypatch.setattr(notebook_preprocessing, 'preprocessing_source',
                        lambda *args: calls.append(args) or original(*args))
    response = client.get('/api/plots/qc/protein/boxplot.png')
    token = response.headers['x-copylot-notebook']
    assert calls == [], 'the render ran the original-file replay'
    assert isinstance(snapshots._entries[token].recipe, PendingRecipe)
    archive = client.get(f'/api/plots/notebooks/{token}.zip')
    assert archive.status_code == 200
    assert len(calls) == 1
    # Prepared once: a second download reuses it.
    assert client.get(f'/api/plots/notebooks/{token}.zip').content == archive.content
    assert len(calls) == 1


def test_a_replay_that_cannot_be_prepared_says_why_on_download(client, monkeypatch):
    token = client.get('/api/plots/qc/protein/cv.png').headers['x-copylot-notebook']
    def mismatch(*args, **kwargs):
        raise notebook_preprocessing.NotebookProvenanceError(
            'Recorded preprocessing does not reproduce this plot input; regenerate annotations.')
    entry = snapshots._entries[token]
    monkeypatch.setattr(entry.recipe, 'finish', mismatch)
    response = client.get(f'/api/plots/notebooks/{token}.zip')
    assert response.status_code == 409
    assert response.json()['detail'] == 'Recorded preprocessing does not reproduce this plot input; regenerate annotations.'


def test_the_notebook_states_its_python_and_checks_its_own_output(client, tmp_path):
    import io
    import platform
    from zipfile import ZipFile
    token = client.get('/api/plots/qc/protein/boxplot.png').headers['x-copylot-notebook']
    blob = client.get(f'/api/plots/notebooks/{token}.zip').content
    with ZipFile(io.BytesIO(blob)) as archive:
        names = archive.namelist()
        notebook = json.loads(archive.read(next(name for name in names if name.endswith('.ipynb'))))
        requirements = archive.read('requirements.txt').decode()
        manifest = json.loads(archive.read('manifest.json'))
    minimum = '.'.join(platform.python_version_tuple()[:2])
    assert requirements.startswith(f'# Python {minimum} or newer is required')
    assert manifest['pythonRequires'] == f'>={minimum}'
    first_code = ''.join(next(cell for cell in notebook['cells'] if cell['cell_type'] == 'code')['source'])
    assert first_code.startswith('import sys\nif sys.version_info < (')
    last = ''.join(notebook['cells'][-1]['source'])
    assert "rglob('original.*')" in last and 'byte-identical' in last


@pytest.mark.parametrize('font', ['helvetica'])
def test_the_manifest_records_the_face_a_font_choice_resolved_to(client, font):
    import io
    from zipfile import ZipFile
    from app.services.plot_styling import PLOT_FONTS, installed_family
    response = client.get('/api/plots/qc/protein/boxplot.png', params={'advanced': json.dumps({'fontFamily': font})})
    blob = client.get(f"/api/plots/notebooks/{response.headers['x-copylot-notebook']}.zip").content
    with ZipFile(io.BytesIO(blob)) as archive:
        manifest = json.loads(archive.read('manifest.json'))
    assert manifest['fonts'] == {font: installed_family(PLOT_FONTS[font][0])}


def test_the_middleware_turns_the_reason_into_a_header(client, monkeypatch):
    from app.services import notebook_qc
    def unavailable(*args, **kwargs):
        raise notebook_preprocessing.NotebookProvenanceError('Original-file processing history is unavailable.')
    monkeypatch.setattr(notebook_preprocessing, 'bind_original_preprocessing', unavailable)
    response = client.get('/api/plots/qc/protein/histogram.png'.replace('histogram', 'intensity-histogram'))
    assert response.status_code == 200
    assert 'x-copylot-notebook' not in response.headers
    assert unquote(response.headers['x-copylot-notebook-unavailable']) == 'Original-file processing history is unavailable.'
    assert notebook_qc  # the QC adapter is the one that swallowed this before


def test_the_last_cell_fails_loudly_on_a_different_figure_and_names_a_missing_font(tmp_path, monkeypatch):
    from pathlib import Path
    from app.services.notebook_archive import _VERIFY_CELL
    (tmp_path / 'resources').mkdir()
    (tmp_path / 'resources' / 'original.png').write_bytes(b'drawn by CoPYlot')
    (tmp_path / 'reproduced.png').write_bytes(b'drawn elsewhere')
    monkeypatch.chdir(tmp_path)
    manifest = {'fonts': {'helvetica': 'A Face Nobody Has'}}
    with pytest.raises(AssertionError, match='A Face Nobody Has'):
        exec(_VERIFY_CELL, {'Path': Path, 'manifest': manifest})
    (tmp_path / 'reproduced.png').write_bytes(b'drawn by CoPYlot')
    exec(_VERIFY_CELL, {'Path': Path, 'manifest': manifest})
