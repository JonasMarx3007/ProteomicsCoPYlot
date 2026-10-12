from notebook_replay_support import set_original_path

import io
import json
import subprocess
import sys
from zipfile import ZipFile

import pandas as pd
import pytest

from app.services import peptide_tools
from app.services.dataset_store import save_peptide_path
from app.services.notebook_archive import build_notebook_archive
from app.services.notebook_sequence import capture_sequence_coverage
from app.services.notebook_snapshots import snapshots
from app.services.session_context import get_session_id


@pytest.fixture
def sequence_input(tmp_path, monkeypatch):
    frame = pd.DataFrame({'ProteinNames': ['OTHER; TEST_HUMAN'] * 5 + ['OTHER'],
        'Stripped.Sequence': ['AAA', 'ABC', 'MISSING', 'PEPTIDE', 'AAA', 'D'],
        # Positive quantities: since 2026-10-02 a peptide with no quantity above 0
        # was not measured and does not cover sequence.
        'Precursor.Quantity': [1.] * 6, 'File.Name': [r'C:\private_sequence_origin\run.raw'] * 6})
    path = tmp_path / 'peptides.csv'
    frame.to_csv(path, index=False)
    save_peptide_path(str(path))
    database = pd.DataFrame([
        ('sp|WRONG|OTHER', 'ZZZZ', 'OTHER', 'TEST_HUMAN'),
        ('sp|P00001|TEST_HUMAN', 'AAAAABCDPEPTIDEABC', 'TEST_HUMAN', 'P00001'),
        ('sp|P00002|TEST_HUMAN', 'WRONG', 'TEST_HUMAN', 'P00002'),
    ], columns=['full_header', 'V1', 'name', 'accession'])
    monkeypatch.setattr(peptide_tools, '_load_fasta_dataframe', lambda species: database.copy())
    return frame, database


@pytest.mark.parametrize('species', ['human', 'mouse'])
@pytest.mark.parametrize('chunk_size', [10, 30])
def test_exact_sequence_map_and_independent_replay(sequence_input, tmp_path, species, chunk_size):
    settings = dict(species=species, protein='TEST_HUMAN', chunk_size=chunk_size)
    expected = peptide_tools.peptide_sequence_coverage(**settings)
    actual = capture_sequence_coverage(**settings)
    recipe = snapshots.get(get_session_id(), actual.pop('notebookToken'))
    assert actual == expected
    assert actual['assignedPeptideCount'] == 4
    assert actual['matchingPeptideCount'] == 3
    assert actual['unmappedPeptides'] == ['MISSING']
    assert actual['coveragePercent'] == round(17 / 18 * 100, 2)
    reference = pd.read_parquet(io.BytesIO(recipe.resources['reference.parquet']))
    assert reference.accession.tolist() == ['P00001']
    _, blob = build_notebook_archive(recipe)
    with ZipFile(io.BytesIO(blob)) as archive:
        assert all(b'private_sequence_origin' not in archive.read(name) for name in archive.namelist())
        archive.extractall(tmp_path)
        name = next(name for name in archive.namelist() if name.endswith('.ipynb'))
    notebook = json.loads((tmp_path / name).read_text())
    cells = '\n'.join(''.join(c['source']) for c in notebook['cells'] if c['cell_type'] == 'code')
    cells = set_original_path(cells, tmp_path)
    run = subprocess.run([sys.executable, '-I', '-c', "import sys;sys.path.insert(0,'.');\n" + cells],
        cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    assert (tmp_path / 'reproduced_coverage.txt').read_text(encoding='utf-8') == expected['sequenceText']
    assert json.loads((tmp_path / 'reproduced_summary.json').read_text()) == expected


def test_sequence_snapshot_route_immutable_and_owned(sequence_input, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes_peptide import router
    from app.api.routes_plots import router as plots_router
    from app.services.session_context import set_session_id, reset_session_id
    monkeypatch.setenv('COPYLOT_SESSION_ISOLATION', '1')
    app = FastAPI()
    app.include_router(router)
    app.include_router(plots_router)
    with TestClient(app) as client:
        response = client.get('/api/peptide/sequence-coverage', params={'species': 'human', 'protein': 'TEST_HUMAN'})
        assert response.status_code == 200
        url = '/api/plots/notebooks/' + response.json()['notebookToken'] + '.zip'
        first = client.get(url)
        sequence_input[1]['V1'] = 'CHANGED'
        assert client.get(url).content == first.content
        owner = set_session_id('other-sequence-owner')
        try:
            assert client.get(url).status_code == 404
        finally:
            reset_session_id(owner)


def test_a_peptide_never_quantified_covers_nothing_on_screen_or_in_the_notebook(tmp_path, monkeypatch):
    """The route serves the notebook's result, so it has to apply the app's quantity rule too."""
    frame = pd.DataFrame({'ProteinNames': ['TEST_HUMAN'] * 3,
        'Stripped.Sequence': ['AAA', 'PEPTIDE', 'DDD'],
        'Precursor.Quantity': [1.0, 0.0, 1.0], 'File.Name': ['run.raw'] * 3})
    path = tmp_path / 'peptides.csv'
    frame.to_csv(path, index=False)
    save_peptide_path(str(path))
    database = pd.DataFrame([('sp|P00001|TEST_HUMAN', 'AAAPEPTIDEDDD', 'TEST_HUMAN', 'P00001')],
        columns=['full_header', 'V1', 'name', 'accession'])
    monkeypatch.setattr(peptide_tools, '_load_fasta_dataframe', lambda species: database.copy())
    settings = dict(species='human', protein='TEST_HUMAN', chunk_size=30)
    expected = peptide_tools.peptide_sequence_coverage(**settings)
    actual = capture_sequence_coverage(**settings)
    actual.pop('notebookToken')
    assert actual == expected
    assert actual['coveragePercent'] == round(6 / 13 * 100, 2)
