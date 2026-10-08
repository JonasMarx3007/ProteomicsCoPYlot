"""Fixtures several notebook-export test modules share."""
import numpy as np
import pandas as pd
import pytest

from app.schemas.annotation import AnnotationFilterConfig
from app.schemas.data_tools import ImputationRunRequest
from app.services.annotation_store import reset_all_annotations, save_annotation
from app.services.data_tools import run_imputation
from app.services.dataset_store import reset_all_datasets, save_peptide_path, save_table_dataset
from app.services.peptide_metadata_store import save_peptide_metadata


@pytest.fixture
def inputs():
    reset_all_datasets()
    reset_all_annotations()
    samples = [f'{group}{i}' for group in 'ABCD' for i in range(1, 5)]
    frame = pd.DataFrame(np.random.default_rng(27).normal(12, 2, (15, 16)), columns=samples)
    frame['ProteinNames'] = [f'P{i}' for i in range(15)]
    frame['GeneNames'] = [f'G{i}' for i in range(15)]
    frame.loc[0, 'A1'] = np.nan
    frame.loc[1, ['A1', 'A2', 'A3']] = np.nan
    frame.loc[2, ['B1', 'B2', 'B3']] = np.nan
    save_table_dataset('example.tsv', 'protein', frame)
    save_annotation(kind='protein', source_data=frame, log2_data=frame, filtered_data=frame.iloc[:-1],
        metadata=pd.DataFrame({'sample': samples, 'condition': [s[0] for s in samples], 'pair_id': [s[1] for s in samples]}),
        is_log2_transformed=True, metadata_source='manual', filter_config=AnnotationFilterConfig(),
        auto_detected=False, warnings=[])
    run_imputation(ImputationRunRequest(kind='protein', seed=77, sampleWise=True))
    yield
    reset_all_datasets()
    reset_all_annotations()


@pytest.fixture
def phosphosites():
    samples = [f'{group}{i}' for group in 'AB' for i in range(1, 5)]
    frame = pd.DataFrame(np.random.default_rng(17).normal(12, 2, (12, 8)), columns=samples)
    frame['Protein_group'] = [f'P{i // 3}' for i in range(12)]
    frame['Gene_group'] = frame['Protein_group']
    frame['PTM_Collapse_key'] = [f'K{i}' for i in range(12)]
    frame['PTM_localization'] = [f'S{i}' for i in range(12)]
    frame['UPD_seq'] = [f'SEQ{i}' for i in range(12)]
    frame.loc[0, samples[0]] = np.nan
    save_table_dataset('sites.csv', 'phospho', frame)
    save_annotation(kind='phospho', source_data=frame, log2_data=frame, filtered_data=frame,
        metadata=pd.DataFrame({'sample': samples, 'condition': ['A'] * 4 + ['B'] * 4}),
        is_log2_transformed=True, metadata_source='manual', filter_config=AnnotationFilterConfig(),
        auto_detected=False, warnings=[])
    run_imputation(ImputationRunRequest(kind='phospho', seed=87, sampleWise=False))


@pytest.fixture
def peptide_input(tmp_path):
    frame = pd.DataFrame({
        'File.Name': ['run1'] * 5 + ['run2'] * 4 + ['outside3'],
        'Stripped.Sequence': ['AAA', 'AAA', 'AAA', 'BBB', 'CCC', 'AAA', 'AAA', 'BBB', 'CCC', 'OUT'],
        'Precursor.Id': ['AAA2', 'AAA2', 'AAA3', 'BBB2', 'CCC2', 'AAA2', 'AAA3', 'BBB2', 'CCC2', 'OUT2'],
        'Precursor.Quantity': [1., 2., 3., 0., np.inf, 4., 5., 6., np.nan, 10.],
        'Alternative.Quantity': [0., 0., 0., 7., 0., 0., 0., 8., 0., 99.],
    })
    path = tmp_path / 'peptides.csv'
    frame.to_csv(path, index=False)
    save_peptide_path(str(path))
    save_peptide_metadata('metadata.csv', pd.DataFrame({'sample': ['run1', 'run2'], 'condition': ['A', 'B']}))
    return path
