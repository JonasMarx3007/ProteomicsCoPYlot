import base64
import io
import json
import re
import subprocess
import sys
from zipfile import ZipFile

import numpy as np
import pandas as pd
import pytest

from app.schemas.annotation import AnnotationFilterConfig
from app.schemas.summary import SummaryReportRequest, SummaryReportContext, SummaryVolcanoEntry
from app.services.annotation_store import save_annotation
from app.services.dataset_store import save_table_dataset
from app.services.notebook_archive import build_notebook_archive
from app.services.notebook_qc import snapshots
from app.services.notebook_report import report_with_notebook
from app.services.report_function import report_function
from app.services.session_context import get_session_id


@pytest.fixture
def report_data(tmp_path):
    from app.services.dataset_store import reset_all_datasets
    from app.services.annotation_store import reset_all_annotations
    reset_all_datasets()
    reset_all_annotations()
    samples = [f'run_{i}' for i in range(6)]
    frame = pd.DataFrame(np.random.default_rng(3).integers(10, 20, (30, 6)).astype(float), columns=samples)
    frame.insert(0, 'ProteinNames', [f'P{i}' for i in range(30)])
    frame.insert(1, 'GeneNames', [f'G{i}' for i in range(30)])
    frame.loc[0, samples[0]] = np.nan
    meta = pd.DataFrame({'sample': samples, 'condition': ['A'] * 3 + ['B'] * 3})
    save_table_dataset(filename=r'C:\private\example.csv', kind='protein', frame=frame)
    save_annotation(kind='protein', source_data=frame, metadata=meta, log2_data=frame,
        filtered_data=frame, is_log2_transformed=True, metadata_source='manual',
        filter_config=AnnotationFilterConfig(), auto_detected=False, warnings=[], log2_auto_detected=False)
    original = tmp_path / 'example.csv'
    frame.to_csv(original, index=False)
    return original


@pytest.mark.parametrize('interactive', [False, True])
def test_complete_report_replays_every_plot_and_table(report_data, tmp_path, interactive):
    from app.services.notebook_report import _active
    from app.services.notebook_preprocessing import report_recipe_sink
    context = SummaryReportContext(qcSettings={'protein': {
        'coverage': {'summary': True, 'dpi': 72}, 'box': {'mode': 'Single', 'dpi': 72},
        'hist': {'dpi': 72}, 'cv': {'dpi': 72}, 'correlation': {'dpi': 72},
        'pca': {'type': 'Interactive' if interactive else 'Normal', 'dpi': 72},
        'abundance': {'type': 'Interactive' if interactive else 'Normal', 'dpi': 72}}},
        volcanoEntries=[SummaryVolcanoEntry(kind='protein', condition1='A', condition2='B',
            renderType='Interactive' if interactive else 'Normal')])
    request = SummaryReportRequest(title='Reproducibility report', reportContext=context)
    result = report_with_notebook(report_function, request)
    assert result.warnings == []
    assert result.notebookError is None
    assert result.notebookToken
    assert _active.get() is None and report_recipe_sink.get() is None
    recipe = snapshots.get(get_session_id(), result.notebookToken)
    sections = recipe.provenance['sections']
    assert len(sections) == 10  # Mapping + eight QC figures + volcano, with paired tables.
    assert recipe.provenance['originalFiles'] == {'protein': 'example.csv'}
    assert any(section['provenance'].get('plot') == 'volcano' for section in sections)
    _assert_replay(result, {'protein': report_data}, tmp_path)


def _assert_replay(result, originals, tmp_path):
    recipe = snapshots.get(get_session_id(), result.notebookToken)
    filename, blob = build_notebook_archive(recipe)
    assert build_notebook_archive(recipe) == (filename, blob)
    root = tmp_path / 'export'
    with ZipFile(io.BytesIO(blob)) as archive:
        for name in archive.namelist():
            assert b'C:\\private' not in archive.read(name)
        archive.extractall(root)
        notebook_name = next(name for name in archive.namelist() if name.endswith('.ipynb'))
    notebook = json.loads((root / notebook_name).read_text())
    code = '\n'.join(''.join(cell['source']) for cell in notebook['cells'] if cell['cell_type'] == 'code')
    for kind, path in originals.items():
        code = code.replace(f'{json.dumps(kind)}: Path("YOUR_ORIGINAL_DATA_FILE")',
                            f'{json.dumps(kind)}: Path({str(path)!r})')
    completed = subprocess.run([sys.executable, '-I', '-'],
        input="import sys; sys.path.insert(0, '.');\n" + code,
        cwd=root, capture_output=True, text=True, timeout=180, encoding='utf-8')
    assert completed.returncode == 0, completed.stderr
    report_images = [base64.b64decode(value) for value in re.findall(r"<img src='data:image/png;base64,([^']+)'", result.html)]
    reproduced = list((root / 'outputs').glob('*/reproduced.png'))
    assert len(reproduced) == len(report_images)
    assert all(path.read_bytes() in report_images for path in reproduced)
    assert len(list((root / 'outputs').glob('*/reproduced_table.csv'))) >= 5
    for original in (root / 'resources').glob('*/original.html'):
        assert (root / 'outputs' / original.parent.name / 'reproduced.html').read_text(encoding='utf-8') == original.read_text(encoding='utf-8')


def _mixed_project(tmp_path, render_type='Normal'):
    """Protein, phosphosite and peptide data with an imputed protein volcano.

    Returns the report context that asks for every QC tab at both levels, and
    the original files the exported notebook will be pointed at.
    """
    from app.services.dataset_store import save_peptide_path
    from app.services.peptide_metadata_store import save_peptide_metadata
    from app.services.annotation_store import get_annotation
    from app.services.data_tools import run_imputation
    from app.schemas.data_tools import ImputationRunRequest
    annotation = get_annotation('protein')
    sites = annotation.source_data.copy()
    sites['Protein_group'] = sites['ProteinNames']
    sites['Gene_group'] = sites['GeneNames']
    sites['PTM_Collapse_key'] = [f'P{i}~S{i}_M1' for i in range(len(sites))]
    sites['UPD_seq'] = [f'PEPS*TIDE{i}' for i in range(len(sites))]
    sites['PTM_localization'] = [.99, .5, np.nan] * 10
    sites['site_num'] = 1
    save_table_dataset('sites.csv', 'phospho', sites)
    save_annotation(kind='phospho', source_data=sites, metadata=annotation.metadata.copy(),
        log2_data=sites, filtered_data=sites, is_log2_transformed=True, metadata_source='manual',
        filter_config=AnnotationFilterConfig(), auto_detected=False, warnings=[])
    site_path = tmp_path / 'sites.csv'
    sites.to_csv(site_path, index=False)
    sequences = ['AKR', 'PEPTIDEK', 'MPEPRK', 'ARPK']
    peptides = pd.DataFrame([{'File.Name': sample, 'Stripped.Sequence': seq,
        'Modified.Sequence': seq, 'Precursor.Id': seq + '2', 'Precursor.Quantity': float(i + 1),
        'RT': float(10 + i), 'Predicted.RT': float(11 + i)}
        for sample in annotation.metadata['sample'] for i, seq in enumerate(sequences)])
    peptide_path = tmp_path / 'peptides.csv'
    peptides.to_csv(peptide_path, index=False)
    save_peptide_path(str(peptide_path))
    save_peptide_metadata('metadata.csv', annotation.metadata.copy())
    run_imputation(ImputationRunRequest(kind='protein', seed=77, sampleWise=True))
    # The PCA and abundance tabs have an interactive variant of their own.
    interactive = {} if render_type == 'Normal' else {
        'pca': {'type': render_type}, 'abundance': {'type': render_type}}
    context = SummaryReportContext(qcSettings={kind: {
        tab: {'dpi': 72, **interactive.get(tab, {})}
        for tab in ['coverage', 'hist', 'box', 'cv', 'pca', 'abundance', 'correlation']}
        for kind in ['protein', 'phospho']},
        volcanoEntries=[SummaryVolcanoEntry(kind='protein', condition1='A', condition2='B',
            dataSource='imputed', renderType=render_type)])
    return context, site_path, peptide_path


def test_mixed_report_with_imputed_statistics_replays_all_levels(report_data, tmp_path):
    context, site_path, peptide_path = _mixed_project(tmp_path)
    result = report_with_notebook(report_function, SummaryReportRequest(title='Mixed report', reportContext=context))
    assert result.warnings == []
    assert result.notebookError is None
    assert result.notebookToken
    recipe = snapshots.get(get_session_id(), result.notebookToken)
    assert recipe.uses_imputed_input
    assert set(recipe.provenance['originalFiles']) == {'protein', 'phospho', 'peptide'}
    sections = recipe.provenance['sections']
    assert len(sections) == 26  # Shared mapping, 24 figures, separate phospho QC summary.
    imputed = [section for section in sections if section['usesImputedInput']]
    assert len(imputed) == 1
    assert imputed[0]['provenance']['plot'] == 'volcano'
    assert imputed[0]['provenance']['imputation']['seed'] == 77
    _assert_replay(result, {'protein': report_data, 'phospho': site_path, 'peptide': peptide_path}, tmp_path)


def test_a_section_that_cannot_be_exported_is_named_and_the_rest_is_still_offered(report_data, monkeypatch):
    """One unexportable figure used to withhold the whole report notebook."""
    from app.services import notebook_report
    original = notebook_report._render
    def render(name, *args, **options):
        if name == 'qc_cv_plot':
            raise ValueError('unavailable')
        return original(name, *args, **options)
    monkeypatch.setattr(notebook_report, '_render', render)
    context = SummaryReportContext(qcSettings={'protein': {'cv': {'dpi': 72}, 'box': {'dpi': 72}}})
    result = report_with_notebook(report_function, SummaryReportRequest(reportContext=context))
    assert 'data:image/png;base64,' in result.html
    assert result.notebookToken and result.notebookError is None
    assert result.notebookOmitted == ['Protein — Coefficient of Variation']
    recipe = snapshots.get(get_session_id(), result.notebookToken)
    assert recipe.provenance['omittedSections'] == ['Protein — Coefficient of Variation']
    assert 'Protein — Coefficient of Variation' in recipe.input_explanation
    names = [section['name'] for section in recipe.provenance['sections']]
    assert any('Boxplot' in name for name in names) and not any('Variation' in name for name in names)


def test_volcano_counts_are_reproduced_and_warnings_stay_out_of_the_export(report_data, tmp_path):
    context = SummaryReportContext(volcanoEntries=[SummaryVolcanoEntry(kind='protein', condition1='A', condition2='B')])
    result = report_with_notebook(report_function, SummaryReportRequest(reportContext=context))
    recipe = snapshots.get(get_session_id(), result.notebookToken)
    volcano = next(section for section in recipe.provenance['sections'] if section['provenance'].get('plot') == 'volcano')
    assert 'warnings' not in volcano['provenance']
    counts = json.loads(recipe.resources[f"{volcano['section']}/counts.json"])
    sentence = re.search(r'([\d,]+) proteins? upregulated in A and ([\d,]+) downregulated .*?out of ([\d,]+) tested '
                         r'proteins?; ([\d,]+) not significant', result.html)
    assert sentence, 'the report states the counts'
    assert [int(value.replace(',', '')) for value in sentence.groups()] == [
        counts['upregulated'], counts['downregulated'], counts['tested'], counts['notSignificant']]
    _assert_replay(result, {'protein': report_data}, tmp_path)
    reproduced = json.loads((tmp_path / 'export' / 'outputs' / volcano['section'] / 'reproduced_counts.json').read_text())
    assert reproduced == counts


def test_report_capture_context_is_reset_when_builder_fails():
    from app.services.notebook_report import _active
    from app.services.notebook_preprocessing import report_recipe_sink
    def fail(_):
        raise RuntimeError('failed')
    with pytest.raises(RuntimeError):
        report_with_notebook(fail, SummaryReportRequest())
    assert _active.get() is None and report_recipe_sink.get() is None


def test_report_snapshot_is_frozen_and_session_owned(monkeypatch):
    from app.schemas.summary import SummaryReportResponse
    from app.services.notebook_report import record_sample_mapping
    from app.services.functions import sample_label_frame
    from app.services.session_context import set_session_id, reset_session_id
    from app.api.routes_plots import download_plot_notebook
    from fastapi import HTTPException
    monkeypatch.setenv('COPYLOT_SESSION_ISOLATION', '1')
    metadata = pd.DataFrame({'sample': ['sample1'], 'condition': ['A']})
    def builder(_):
        record_sample_mapping('Protein', sample_label_frame(metadata))
        return SummaryReportResponse(fileName='report.html', html='<html/>')
    owner = set_session_id('report-owner-123')
    try:
        result = report_with_notebook(builder, SummaryReportRequest())
        response = download_plot_notebook(result.notebookToken)
        metadata.loc[0, 'condition'] = 'Changed after report generation'
        assert download_plot_notebook(result.notebookToken).body == response.body
        assert response.headers['cache-control'] == 'no-store'
        other = set_session_id('report-other-123')
        try:
            with pytest.raises(HTTPException) as exc:
                download_plot_notebook(result.notebookToken)
            assert exc.value.status_code == 404
        finally:
            reset_session_id(other)
    finally:
        reset_session_id(owner)


def test_changed_dataset_does_not_publish_a_mixed_report_snapshot(monkeypatch):
    from app.schemas.summary import SummaryReportResponse
    from app.services import runtime_cache
    revision = [1]
    monkeypatch.setattr(runtime_cache, 'runtime_cache_version', lambda: revision[0])
    def builder(_):
        revision[0] += 1
        return SummaryReportResponse(fileName='report.html', html='<html/>')
    result = report_with_notebook(builder, SummaryReportRequest())
    assert result.notebookToken is None
    assert result.notebookError


@pytest.mark.parametrize('render_type', ['Normal', 'Interactive'])
def test_every_report_render_is_connected_to_notebook_capture(report_data, tmp_path, monkeypatch, render_type):
    """Every figure or table the report renders is captured for the notebook.

    The report draws through three guards (`_safe_png`, `_safe_plotly`,
    `_safe_table_html`), each handed a renderer. A renderer that calls the plot
    function directly instead of through `report_plot` / `report_table` still
    draws the report, but leaves that figure out of the exported notebook. Each
    guard is wrapped here to count how many captures its renderer made, while
    the report for every QC tab at every level (plus a volcano) is built.
    """
    import app.services.report_function as report_module

    captures = {'count': 0}

    def counting(adapter):
        def wrapper(*args, **options):
            captures['count'] += 1
            return adapter(*args, **options)
        return wrapper

    monkeypatch.setattr(report_module, 'report_plot', counting(report_module.report_plot))
    monkeypatch.setattr(report_module, 'report_table', counting(report_module.report_table))

    uncaptured: list[str] = []
    guarded = {'count': 0}

    def checking(guard):
        def wrapper(*, renderer, fallback_title, **options):
            before = captures['count']
            guarded['count'] += 1
            content = guard(renderer=renderer, fallback_title=fallback_title, **options)
            if captures['count'] != before + 1:
                uncaptured.append(f'{guard.__name__}: {fallback_title}')
            return content
        return wrapper

    for name in ('_safe_png', '_safe_plotly', '_safe_table_html'):
        monkeypatch.setattr(report_module, name, checking(getattr(report_module, name)))

    context, _, _ = _mixed_project(tmp_path, render_type=render_type)
    result = report_with_notebook(report_function, SummaryReportRequest(title='Capture report', reportContext=context))

    assert result.warnings == []
    assert guarded['count'] >= 20, f"only {guarded['count']} renders were exercised"
    assert not uncaptured, f'rendered without notebook capture: {uncaptured}'
