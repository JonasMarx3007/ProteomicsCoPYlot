import io
import json

import pandas as pd
import pytest

from app.schemas.annotation import IdentifierTranslationStep
from app.schemas.data_tools import IdTranslationRequest
from app.services import id_translation
from app.services.dataset_store import get_current_dataset, save_table_dataset


@pytest.mark.parametrize('suffix,separator', [('csv', ','), ('tsv', '\t')])
@pytest.mark.parametrize('output_db,output_column', [('HGNC Symbol', 'GeneNames'), ('Ensembl', 'EnsemblNames')])
def test_missing_translations_counts_exports_and_history(monkeypatch, suffix, separator, output_db, output_column):
    database = pd.DataFrame({'uniprot_symbol': ['P1', 'P2'], 'symbol': ['G1', 'G2'],
                             'ensembl_gene_id': ['E1', 'E2']})
    monkeypatch.setattr(id_translation, 'load_db', lambda: database)
    original = pd.DataFrame({'ProteinNames': ['P1', 'unknown1', 'unknown2', None, '', 'P1;P2', 'unknown;P2', 'P1'],
                             'A1': range(8)})
    save_table_dataset(f'original.{suffix}', 'protein', original)
    request = IdTranslationRequest(kind='protein', column='ProteinNames', inputDb='UniProt Accession',
                                   outputDb=output_db, autoDetectInput=False)
    filename, content, _ = id_translation.export_id_translation(request)
    exported = pd.read_csv(io.BytesIO(content), sep=separator, keep_default_na=False)
    assert filename == f'original_translated.{suffix}'
    assert len(exported) == len(original)
    assert exported.loc[1:4, output_column].tolist() == ['', '', '', '']
    assert exported.ProteinNames.tolist() == original.ProteinNames.fillna('').tolist()
    response = id_translation.run_id_translation(request)
    assert response.translatedCount == 4
    assert response.totalRows == 8
    assert all(response.preview[i][output_column] is None for i in range(1, 5))
    stored = get_current_dataset('protein')
    pd.testing.assert_frame_equal(stored.frame[original.columns], original)
    assert stored.frame.loc[1:4, output_column].isna().all()
    assert stored.frame.loc[1:4, 'GeneNames'].isna().all()
    history = json.loads(stored.id_translations[0].model_dump_json())
    key = id_translation.translation_key('unknown1')
    assert history['outputs'][output_column][key] is None
    validated = IdentifierTranslationStep.model_validate(history).model_dump()
    pd.testing.assert_frame_equal(id_translation.replay_id_translations(original, [validated]), stored.frame)


def test_all_unmapped_stay_missing(monkeypatch):
    monkeypatch.setattr(id_translation, 'load_db', lambda: pd.DataFrame({'uniprot_symbol': ['P1'], 'symbol': ['G1']}))
    original = pd.DataFrame({'ProteinNames': ['unknown1', 'unknown2']})
    save_table_dataset('original.csv', 'protein', original)
    result = id_translation.run_id_translation(IdTranslationRequest(kind='protein', column='ProteinNames',
        inputDb='UniProt Accession', outputDb='HGNC Symbol', autoDetectInput=False))
    assert result.translatedCount == 0
    assert result.totalRows == 2
    assert get_current_dataset('protein').frame.GeneNames.isna().all()


def test_nullable_existing_output_serializes_missing(monkeypatch):
    monkeypatch.setattr(id_translation, 'load_db', lambda: pd.DataFrame({'symbol': ['G1'], 'uniprot_gene': ['NEW1']}))
    original = pd.DataFrame({'GeneNames': pd.Series(['G1', pd.NA], dtype='string'), 'ProteinNames': ['P1', 'P2']})
    save_table_dataset('original.csv', 'protein', original)
    result = id_translation.run_id_translation(IdTranslationRequest(kind='protein', column='GeneNames',
        inputDb='HGNC Symbol', outputDb='UniProt Gene', autoDetectInput=False))
    stored = get_current_dataset('protein')
    history = json.loads(stored.id_translations[0].model_dump_json())
    assert result.translatedCount == 1
    assert stored.frame.GeneNames.isna().tolist() == [False, True]
    assert stored.frame.ProteinNames.tolist() == ['P1', 'P2']
    pd.testing.assert_frame_equal(id_translation.replay_id_translations(original, [history]), stored.frame)
