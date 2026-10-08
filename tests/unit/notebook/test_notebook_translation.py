import io
import json
import subprocess
import sys
from zipfile import ZipFile

import numpy as np
import pandas as pd
import pytest

from app.api.routes_annotations import generate_annotation
from app.schemas.annotation import AnnotationGenerateRequest
from app.schemas.data_tools import IdTranslationRequest
from app.services import id_translation
from app.services.dataset_reader import read_dataframe
from app.services.dataset_store import get_current_dataset, save_table_dataset
from app.services.notebook_archive import build_notebook_archive
from app.services.notebook_qc import snapshots
from app.services.notebook_single import render_box
from app.services.session_context import get_session_id


@pytest.fixture
def translated_input(tmp_path, monkeypatch):
    database = pd.DataFrame({'uniprot_symbol': ['P1', 'P2'], 'symbol': ['G1', 'G2'],
        'ensembl_gene_id': ['E1', 'E2'], 'uniprot_gene': ['UPG1', 'UPG2']})
    monkeypatch.setattr(id_translation, 'load_db', lambda: database)
    raw = pd.DataFrame(np.random.default_rng(28).uniform(8, 16, (6, 6)),
        columns=['A1', 'A2', 'A3', 'B1', 'B2', 'B3'])
    raw['ProteinNames'] = ['P1', 'P2', 'P1;P2', None, 'unknown', 'P1']
    path = tmp_path / 'original.tsv'
    raw.to_csv(path, sep='\t', index=False)
    with path.open('rb') as stream:
        frame = read_dataframe(path.name, stream)
    save_table_dataset(path.name, 'protein', frame, source_path=str(path))
    id_translation.run_id_translation(IdTranslationRequest(kind='protein', column='ProteinNames',
        inputDb='UniProt Accession', outputDb='Ensembl', autoDetectInput=False))
    id_translation.run_id_translation(IdTranslationRequest(kind='protein', column='GeneNames',
        inputDb='HGNC Symbol', outputDb='UniProt Gene', autoDetectInput=False))
    generate_annotation(AnnotationGenerateRequest(kind='protein', isLog2Transformed=True,
        conditions=[{'name': g, 'columns': [f'{g}{i}' for i in range(1, 4)]} for g in 'AB']))
    return path, frame


@pytest.mark.parametrize('restore', [False, True])
def test_translation_history_replays_original_file_without_database(translated_input, tmp_path, restore, monkeypatch):
    from app.services.restore_state import export_state_blob, decode_restore_blob, apply_restore_state
    path, original = translated_input
    history = [step.model_dump() for step in get_current_dataset('protein').id_translations]
    assert len(history) == 2 and set(history[0]['outputs']) == {'EnsemblNames', 'GeneNames'}
    if restore:
        state = decode_restore_blob(export_state_blob(portable=True))
        assert str(path) not in json.dumps(state)
        apply_restore_state(state, {})
        assert [step.model_dump() for step in get_current_dataset('protein').id_translations] == history
    monkeypatch.setattr(id_translation, 'load_db', lambda: pytest.fail('Historical replay must not query today\'s database'))
    image, token = render_box(kind='protein', protein='UPG1', identifier='genes', conditions=['A', 'B'], dpi=80)
    recipe = snapshots.get(get_session_id(), token)
    assert recipe.provenance['preprocessing']['id_translations'] == history
    _, payload = build_notebook_archive(recipe)
    with ZipFile(io.BytesIO(payload)) as archive:
        assert all(str(path).encode() not in archive.read(name) for name in archive.namelist())
        archive.extractall(tmp_path)
        name = next(name for name in archive.namelist() if name.endswith('.ipynb'))
    notebook = json.loads((tmp_path / name).read_text())
    code = '\n'.join(''.join(cell['source']) for cell in notebook['cells'] if cell['cell_type'] == 'code')
    code = code.replace("Path('YOUR_ORIGINAL_DATA_FILE')", "Path('original.tsv')")
    result = subprocess.run([sys.executable, '-I', '-c', "import sys;sys.path.insert(0,'.');\n" + code],
        cwd=tmp_path, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / 'reproduced.png').read_bytes() == image
    rebuilt = id_translation.replay_id_translations(original, history)
    pd.testing.assert_frame_equal(rebuilt, get_current_dataset('protein').frame)
    altered = original.copy()
    altered.loc[0, 'ProteinNames'] = 'UNRECORDED'
    with pytest.raises(ValueError, match='outside the recorded translation'):
        id_translation.replay_id_translations(altered, history)


def test_replacement_upload_clears_translation_history(translated_input):
    _, original = translated_input
    stored = save_table_dataset('replacement.tsv', 'protein', original)
    assert stored.id_translations == []


def test_replay_preserves_existing_nullable_identifier_dtype():
    original = pd.DataFrame({'GeneNames': pd.Series(['G1', pd.NA], dtype='string')})
    translated = original.copy()
    translated.loc[:, 'GeneNames'] = ['NEW1', 'NA']
    keys = original.GeneNames.map(id_translation.translation_key)
    step = {'sourceColumn': 'GeneNames', 'outputs': {'GeneNames': dict(zip(keys, ['NEW1', 'NA']))}}
    pd.testing.assert_frame_equal(id_translation.replay_id_translations(original, [step]), translated)


def test_translation_after_annotation_withholds_notebook(translated_input):
    id_translation.run_id_translation(IdTranslationRequest(kind='protein', column='GeneNames',
        inputDb='UniProt Gene', outputDb='HGNC Symbol', autoDetectInput=False))
    image, token = render_box(kind='protein', protein='UPG1', identifier='genes', conditions=['A', 'B'], dpi=80)
    assert image and not token


def test_invalid_restored_history_preserves_the_current_session(translated_input):
    from app.services.restore_state import export_state_blob, decode_restore_blob, apply_restore_state
    stored = get_current_dataset('protein')
    state = decode_restore_blob(export_state_blob(portable=True))
    state['backend']['packages'][0]['datasets']['protein']['idTranslations'] = [{'outputs': 'not a mapping'}]
    with pytest.raises(ValueError):
        apply_restore_state(state, {})
    assert get_current_dataset('protein') is stored


@pytest.mark.parametrize('stage', ['before_collapse', 'after_collapse'])
def test_translation_and_phosphoprotein_collapse_replay(phosphosites, tmp_path, monkeypatch, stage):
    from app.services.phosprot_tools import aggregate_from_phospho
    from app.services.notebook_pca import render_pca
    original = get_current_dataset('phospho').frame.copy()
    original.to_parquet(tmp_path / 'original.parquet')
    database = pd.DataFrame({'uniprot_symbol': [f'P{i}' for i in range(4)],
                            'symbol': [f'NEW{i}' for i in range(4)]})
    monkeypatch.setattr(id_translation, 'load_db', lambda: database)
    if stage == 'after_collapse':
        aggregate_from_phospho('mean', 'non_imputed')
    kind = 'phospho' if stage == 'before_collapse' else 'phosprot'
    column = 'Protein_group' if kind == 'phospho' else 'Phosphoprotein'
    id_translation.run_id_translation(IdTranslationRequest(kind=kind, column=column,
        inputDb='UniProt Accession', outputDb='HGNC Symbol', autoDetectInput=False))
    generate_annotation(AnnotationGenerateRequest(kind=kind, isLog2Transformed=True,
        conditions=[{'name': g, 'columns': [f'{g}{i}' for i in range(1, 5)]} for g in 'AB']))
    if stage == 'before_collapse':
        aggregate_from_phospho('mean', 'non_imputed')
    _, token = render_pca('phosprot', dpi=80)
    recipe = snapshots.get(get_session_id(), token)
    _, payload = build_notebook_archive(recipe)
    with ZipFile(io.BytesIO(payload)) as archive:
        archive.extractall(tmp_path)
        name = next(name for name in archive.namelist() if name.endswith('.ipynb'))
    notebook = json.loads((tmp_path / name).read_text())
    code = '\n'.join(''.join(cell['source']) for cell in notebook['cells'] if cell['cell_type'] == 'code')
    code = code.replace("Path('YOUR_ORIGINAL_DATA_FILE')", "Path('original.parquet')")
    result = subprocess.run([sys.executable, '-I', '-c', "import sys;sys.path.insert(0,'.');\n" + code],
        cwd=tmp_path, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr


def test_a_render_without_a_notebook_says_why_under_the_plot(translated_input):
    """The page is told why there is no notebook (tests/unit/notebook/test_notebook_export_preparation.py)."""
    from app.schemas.data_tools import IdTranslationRequest
    from app.services import id_translation
    from app.services.notebook_single import render_box
    from app.services.plot_export import notebook_unavailable
    id_translation.run_id_translation(IdTranslationRequest(kind='protein', column='GeneNames',
        inputDb='UniProt Gene', outputDb='HGNC Symbol', autoDetectInput=False))
    holder: dict = {}
    reset = notebook_unavailable.set(holder)
    try:
        image, token = render_box(kind='protein', protein='UPG1', identifier='genes', conditions=['A', 'B'], dpi=80)
    finally:
        notebook_unavailable.reset(reset)
    assert image and not token
    assert holder['reason'] == 'Regenerate annotations after identifier translation before exporting a notebook.'
