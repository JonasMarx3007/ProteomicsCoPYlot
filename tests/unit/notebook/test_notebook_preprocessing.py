import io
import json
import os
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

import numpy as np
import pandas as pd
import pytest

from app.api.routes_annotations import generate_annotation
from app.schemas.annotation import AnnotationGenerateRequest, AnnotationFilterConfig
from app.services.dataset_reader import read_dataframe
from app.services.dataset_store import save_table_dataset
from app.services.notebook_archive import build_notebook_archive
from app.services.notebook_comparison import render_comparison
from app.services.notebook_qc import snapshots
from app.services.session_context import get_session_id


@pytest.mark.parametrize('normalization', [
    'none', 'median', 'quantile', pytest.param('vsn', marks=pytest.mark.requires_r('vsn')),
])
@pytest.mark.parametrize('log2', [False, True])
def test_original_upload_replay(tmp_path, normalization, log2):
    environment = os.environ.copy()
    if normalization == 'vsn':
        from app.services.r_vsn import vsn_availability
        from app.services.r_runtime import detect_r_runtime
        availability = vsn_availability()
        assert availability['available'], availability
        environment['PATH'] = str(Path(detect_r_runtime()['executable']).parent) + os.pathsep + environment.get('PATH', '')
    rows = 200 if normalization == 'vsn' else 12
    raw = pd.DataFrame(np.random.default_rng(9).uniform(5, 15, (rows, 6)),
        columns=['A1', 'A2', 'A3', 'B1', 'B2', 'B3'])
    raw['PG.ProteinGroups'] = [f'P{i}' for i in range(rows)]
    raw.loc[0, 'A1'] = 0
    raw.loc[1, 'B1'] = np.nan
    original = tmp_path / 'original.tsv'
    raw.to_csv(original, sep='\t', index=False)
    with original.open('rb') as stream:
        parsed = read_dataframe(original.name, stream)
    save_table_dataset(original.name, 'protein', parsed)
    generate_annotation(AnnotationGenerateRequest(kind='protein', isLog2Transformed=log2,
        conditions=[{'name': g, 'columns': [f'{g}{i}' for i in range(1, 4)]} for g in 'AB'],
        filter=AnnotationFilterConfig(normalization=normalization, minPresent=2)))
    content, token = render_comparison('pearson', kind='protein', sample1='A1', sample2='B1', dpi=80)
    # Download preparation: the first get finishes the deferred original-file replay.
    recipe = snapshots.get(get_session_id(), token)
    assert recipe.provenance['inputReplay'] == 'original-file'
    _, blob = build_notebook_archive(recipe)
    with ZipFile(io.BytesIO(blob)) as archive:
        archive.extractall(tmp_path)
        notebook_name = next(n for n in archive.namelist() if n.endswith('.ipynb'))
    notebook = json.loads((tmp_path / notebook_name).read_text())
    code = '\n'.join(''.join(c['source']) for c in notebook['cells'] if c['cell_type'] == 'code')
    code = code.replace("Path('YOUR_ORIGINAL_DATA_FILE')", "Path('original.tsv')")
    run = subprocess.run([sys.executable, '-I', '-c', "import sys;sys.path.insert(0,'.');\n" + code],
        cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=90)
    assert run.returncode == 0, run.stderr
    assert (tmp_path / 'reproduced.png').read_bytes() == content
    if normalization == 'median' and not log2:
        changed = raw.copy()
        changed.loc[2, 'A1'] += 1
        changed.to_csv(original, sep='\t', index=False)
        wrong = subprocess.run([sys.executable, '-I', '-c', "import sys;sys.path.insert(0,'.');\n" + code],
            cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=90)
        assert wrong.returncode != 0 and 'AssertionError' in wrong.stderr
    original.unlink()
    missing = subprocess.run([sys.executable, '-I', '-c', "import sys;sys.path.insert(0,'.');\n" + code],
        cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=90)
    assert missing.returncode != 0 and 'FileNotFoundError' in missing.stderr


@pytest.mark.parametrize('extension', ['csv', 'tsv', 'txt', 'xlsx', 'parquet'])
def test_original_reader_matches_upload_parser(tmp_path, extension):
    from app.services.notebook_preprocessing import preprocessing_source
    frame = pd.DataFrame({'PG.ProteinGroups': ['P1', None, 'P3'], 'A1': [0., np.nan, 123.456],
                          'PG.Genes': ['G1', 'G2', None]})
    original = tmp_path / f'original.{extension}'
    if extension == 'xlsx':
        frame.to_excel(original, index=False)
    elif extension == 'parquet':
        frame = pd.concat([frame] * 16_667)
        frame.to_parquet(original)
    else:
        frame.to_csv(original, sep=',' if extension == 'csv' else '\t', index=False)
    with original.open('rb') as stream:
        expected = read_dataframe(original.name, stream)
    namespace = {}
    exec(preprocessing_source().code, namespace)
    pd.testing.assert_frame_equal(namespace['read_original_table'](original), expected, check_exact=True)


def test_vsn_runtime_failure_is_a_recoverable_export_error(monkeypatch):
    from app.services import r_runtime
    from app.services.notebook_preprocessing import vsn_runtime_version
    monkeypatch.setattr(r_runtime, 'detect_r_runtime', lambda: {'executable': 'Rscript'})
    def failed(*args, **kwargs):
        raise subprocess.TimeoutExpired('Rscript', 60)
    monkeypatch.setattr(subprocess, 'run', failed)
    with pytest.raises(ValueError, match='R and Bioconductor vsn'):
        vsn_runtime_version()


@pytest.mark.parametrize('method,mode', [('at_least_n', 'in_at_least_one_group'), ('percentage', 'overall')])
def test_normalization_filter_and_localization_replay_in_app_order(method, mode):
    from app.services.annotation_store import get_annotation
    from app.services.functions import select_matrix
    from app.services.phospho_localization import set_localization_cutoff
    from app.services.notebook_preprocessing import preprocessing_source
    samples = ['A1', 'A2', 'A3', 'B1', 'B2', 'B3']
    raw = pd.DataFrame(np.random.default_rng(12).uniform(5, 50, (12, 6)), columns=samples)
    raw['PTM_Collapse_key'] = [f'P{i}_S1_M1' for i in range(12)]
    raw['PTM_localization'] = [.99, .8, .2, np.nan] * 3
    raw.loc[0, samples[:3]] = 0
    raw.loc[4, samples[:5]] = 0
    filtering = AnnotationFilterConfig(normalization='quantile', method=method, mode=mode,
        minPresent=2, minPercentage=60)
    save_table_dataset('sites.tsv', 'phospho', raw)
    generate_annotation(AnnotationGenerateRequest(kind='phospho', isLog2Transformed=False,
        conditions=[{'name': g, 'columns': [f'{g}{i}' for i in range(1, 4)]} for g in 'AB'], filter=filtering))
    set_localization_cutoff(.75)
    _, expected, metadata = select_matrix('phospho', 'filtered')
    assert 0 < len(expected) < len(raw)
    config = {'kind': 'phospho', 'source': 'filtered', 'is_log2': False,
        'normalization': 'quantile', 'filter': filtering.model_dump(), 'localization_cutoff': .75,
        'linear_output': False}
    namespace = {}
    exec(preprocessing_source().code, namespace)
    actual = namespace['replay_preprocessing'](get_annotation('phospho').source_data, metadata, config)
    pd.testing.assert_frame_equal(actual, expected, check_exact=True)
