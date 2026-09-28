"""Pre-refactor report fingerprints; renderers are deterministic parameter probes."""
import hashlib
import importlib
import json
import re
from datetime import datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from app.schemas.summary import SummaryReportContext, SummaryReportRequest, SummaryVolcanoEntry
from app.services.html_security import GENERATED_HTML_META

report = importlib.import_module('app.services.report_function')
# 2026-09-16: every case that renders a projection moved, because the report now
# asks `qc_pca_feature_summary` how much of the matrix reached the PCA. The
# rendered HTML is byte-identical in all 24 cases -- under this harness the
# summary is one of the stubbed `qc_*` probes, so the completeness sentence
# resolves to nothing; only the recorded call list gained the extra name. The
# sentence itself is covered by test_report_processing_provenance.py.
# 2026-09-17: the six `peptide,...` cases moved, because the summary report now
# passes the page's `Cleavage Rule` through to `peptide_missed_cleavage_plot`
# instead of always rendering under trypsin. Only that one call gained an
# argument (`protease`); under this harness the probe's arguments are what the
# figure's bytes are, so those cases' HTML moves with it. The pass-through
# itself is covered by test_missed_cleavage_reporting.py.
# Layout snapshots use a fixed version; test_report_version_and_ksea_filename
# independently verifies that real reports print the current application version.
# 2026-09-21: the coverage plot's total line became a switch of its own
# (`referenceLine` in the coverage settings), so the report now forwards
# `reference_line=True` to the two coverage renderers. Reverting just that
# argument reproduces the previous hashes; it is the whole difference.
# 2026-09-24: DBSCAN's radius became relative (`dbscan_eps_factor`, x median
# sample distance) instead of an absolute `dbscan_eps`; the PCA renderer
# argument was renamed accordingly. Later the same day the report's projection
# became PCA-only: `method` is always "PCA" and the UMAP/t-SNE arguments are no
# longer forwarded to the renderer. Those renderer arguments are the whole
# difference.
SNAPSHOTS = {
    'qc_custom:': '31e9b3e4680befa02db2ec0566567663337d540546ff762cdaa8127b85e1d920',
    'qc_custom:protein': 'd4bb4d9263319cbf4318dba944eabdca396e8998003839612d953450eba68e6f',
    'qc_custom:phospho': '1cff2a564e52e627c61ae50f6ec832e16f85f3b14389e158d182b70889a8e526',
    'qc_custom:peptide,protein,phospho': '9edecfa9db40bf3ba294a618f57b832f76ba31fd2028a61b251ac0f8e143581c',
    'qc_invalid:': '31e9b3e4680befa02db2ec0566567663337d540546ff762cdaa8127b85e1d920',
    'qc_invalid:protein': '26ef7e6320670b3497461e27dd16a8defcf0ad20b9f21a6a437b5464c771dd9b',
    'qc_invalid:phospho': '49bab6ac069fbcbafb06b4429e647b51aca0634294217d7646ee9e8eadb53243',
    'qc_invalid:peptide,protein,phospho': '8f7fa836923616e322f67710abdd97c39e2697586039894827471bd5ac8f3a3a',
    'default:': '31e9b3e4680befa02db2ec0566567663337d540546ff762cdaa8127b85e1d920',
    # The three `default` snapshots below changed when advanced mode stopped
    # gating the appearance settings: the case's custom PCA title now reaches
    # the PCA renderer with the panel closed, as it reaches the plot on screen.
    # That forwarded title is the whole difference.
    'default:protein': '1dafcc83b0a4f545a0c9f1577bd4cfdf6deb8ecc80f9dc1aac161524f531f712',
    'default:phospho': '7d559d576ebe8c0f245508b557cfd04cc63b17311eb93f9ce64b1edaed4bc3fc',
    'default:peptide,protein,phospho': 'be6d8308e0791286d3ab2db5fe848470a745601b63f4819d3fccdde283f2dfb0',
    'custom:': '31e9b3e4680befa02db2ec0566567663337d540546ff762cdaa8127b85e1d920',
    'custom:protein': '64a0a750e160b91c3ba0410b1b3223826f490fed2642d277c8e7bae86341707e',
    'custom:phospho': '9cfec6587b2665686067ca354f32e56c667c7da1ee3553b36b3dcff19d2a5c4d',
    'custom:peptide,protein,phospho': 'b92ef3643a69465904473f7997913e17b0ec0506cd1a92ca547cefa615cb46bd',
    'interactive:': '31e9b3e4680befa02db2ec0566567663337d540546ff762cdaa8127b85e1d920',
    'interactive:protein': 'aecccec804826debfc03563ea65235dc55955ce2efe1fd4a0853cb2cf502f9e5',
    'interactive:phospho': '33d6fbeb0b3cccee1bc26904d05a66f67a1a2508f7199e495d8f56c582693408',
    'interactive:peptide,protein,phospho': '60d4b066e04b9f6077a83c857dde8d969e2a5625fc894cff831047f1d0896b34',
    'failure:': '31e9b3e4680befa02db2ec0566567663337d540546ff762cdaa8127b85e1d920',
    'failure:protein': 'c38b0df3a997aa1ea9c394891cbfa491bb0b4101978b9682b05e19fddb1b5a55',
    'failure:phospho': 'fef2705d84ee974fad103af62b6f80267f8442d5ac2e7f8ce7119f7b4406021d',
    'failure:peptide,protein,phospho': '03aa537e37f34492ace116f120c8d333198f4c2c4949919840e2d9c320256ef7',
}


def render_case(monkeypatch, kinds, mode, *, pca_scaling=None, selected_settings=False):
    monkeypatch.setattr(report, 'datetime', SimpleNamespace(now=lambda: datetime(2026, 9, 9)))
    comments = {key: [f'{key} <general> & text'] for key in report.GENERAL_COMMENTS}
    monkeypatch.setattr(report, 'GENERAL_COMMENTS', comments)
    monkeypatch.setattr(report, '_load_general_comments', lambda: comments)
    annotation = SimpleNamespace(
        metadata=pd.DataFrame({'sample': ['A', 'B'], 'condition': ['A', 'B']}),
        source_data=pd.DataFrame({'value': [1, 2, 3]}), filtered_data=pd.DataFrame({'value': [1, 2]}),
        filter_config=SimpleNamespace(method='percentage', mode='overall', minPercentage=75, normalization='median'),
        imputation=SimpleNamespace(mode='numerical', downShift=1.8, width=0.3, seed=69, sampleWise=True),
    )
    monkeypatch.setattr(report, 'get_annotation', lambda kind: annotation if kind in kinds else None)
    monkeypatch.setattr(report, 'get_current_dataset', lambda kind: object() if kind in kinds else None)
    calls = []

    def renderer(name):
        def render(*args, **kwargs):
            values = [arg.model_dump() if hasattr(arg, 'model_dump') else arg for arg in args]
            encoded = json.dumps([name, values, kwargs], sort_keys=True)
            calls.append(encoded)
            if mode == 'failure' and 'pca' in name:
                raise ValueError('synthetic <failure> & details')
            if name.endswith('_table'):
                return pd.DataFrame({'Label': ['<A>&'], 'Value': [1.23456789]})
            return encoded if name.endswith('_html') or name == 'volcano_html' else encoded.encode()
        return render

    names = [name for name in vars(report) if name.startswith(('qc_', 'peptide_')) or
             name in ('completeness_missing_value_plot', 'completeness_missing_value_plot_peptide',
                      'phospho_coverage_png', 'phosphosite_plot_png', 'volcano_html')]
    for name in names:
        if callable(getattr(report, name)):
            monkeypatch.setattr(report, name, renderer(name))
    # The per-volcano counts come from run_volcano, which reads the real dataset
    # stores. Stub it deterministically so these fingerprints stay about report
    # structure; the counting itself is covered by test_volcano_report_block.py.
    monkeypatch.setattr(report, 'run_volcano', lambda payload: SimpleNamespace(
        upregulatedCount=312, downregulatedCount=288,
        totalRows=7450, notSignificantCount=6850))
    settings = {} if mode == 'default' else {
        'type': 'Interactive' if mode == 'interactive' else 'Normal', 'dataSource': 'imputed',
        'header': False, 'legend': False, 'plotDim': '3D', 'method': 'UMAP', 'addEllipses': True,
        'dotSize': 90, 'clusterMethod': 'KMeans', 'clusterCount': 1, 'colorBy': 'Sample',
        'umapNNeighbors': 999, 'umapMinDist': -1, 'tsnePerplexity': 2000, 'tsneLearningRate': 1,
        'dbscanEpsFactor': 0, 'dbscanMinSamples': 999, 'randomState': 123, 'widthCm': 90, 'heightCm': 2, 'dpi': 50,
    }
    if pca_scaling is not None:
        settings['scaling'] = pca_scaling
    context = SummaryReportContext(
        qcSettings={kind: {'pca': settings} for kind in ('protein', 'phospho')},
        advancedPlotMode=mode != 'default', qcAdvancedSettingsByTab={'pca': {'title': '<custom> & title'}},
        volcanoEntries=[SummaryVolcanoEntry(kind=kind, condition1='A', condition2='B', dataSource='imputed')
                        for kind in ('protein', 'phospho') if kind in kinds],
    )
    if mode in ('qc_custom', 'qc_invalid'):
        plot_settings = {
            'header': False, 'legend': False, 'widthCm': 32, 'heightCm': 18, 'dpi': 144,
            'mode': 'Median', 'outliers': True, 'includeId': True, 'text': True, 'textSize': 15,
            'method': 'Scatter', 'fullRange': True,
        }
        if mode == 'qc_invalid':
            plot_settings.update(header='false', legend='true', widthCm=-1, heightCm=100, dpi='invalid')
        for kind in ('protein', 'phospho'):
            context.qcSettings[kind].update({
                tab: plot_settings for tab in ('hist', 'box', 'cv', 'abundance', 'correlation')
            })
    if selected_settings:
        for kind in ('protein', 'phospho'):
            context.qcSettings[kind]['abundance'] = {'condition': 'B', 'type': 'Interactive' if mode == 'interactive' else 'Normal'}
        context.qcSettings['peptide'] = {'coverage': {'quantityColumn': 'LFQ intensity'}}
        context.completenessSettings = {'quantityColumn': 'LFQ intensity', 'binCount': 1, 'header': False,
            'text': False, 'textSize': 12, 'color': '#123456', 'widthCm': 25, 'heightCm': 15, 'dpi': 144}
    result = report.report_function(SummaryReportRequest(
        title='Report <title> & test', author='Author <name>', reportContext=context,
        textEntries={'Introduction': 'Intro <safe>\nsecond line', 'PCAProtAbove': 'Before <PCA>',
                     'PCAPhosBelow': 'After & PCA'},
    ))
    return result, calls


@pytest.mark.parametrize('kinds', [(), ('protein',), ('phospho',), ('peptide', 'protein', 'phospho')])
@pytest.mark.parametrize('mode', ['default', 'custom', 'interactive', 'failure', 'qc_custom', 'qc_invalid'])
def test_report_output_and_renderer_arguments_are_unchanged(monkeypatch, kinds, mode):
    monkeypatch.setattr(report, 'VERSION', 'Proteomics CoPYlot V1.0.0')
    result, calls = render_case(monkeypatch, kinds, mode)
    assert result.html.count(GENERATED_HTML_META) == 1
    # Only the newly added policy differs from the pre-hardening report baseline.
    result.html = result.html.replace('\n' + GENERATED_HTML_META, '', 1)
    # R7 intentionally changes only these sentences in this probe harness.
    # Their exact presence/meaning is checked by test_report_processing_provenance.
    # Removing them here proves all remaining HTML and renderer calls are unchanged.
    result.html = re.sub(
        r'<p>QC plots use the (?:normalized, )?unfiltered, non-imputed data unless another data source is stated. '
        r'Filtering and imputation apply to clustering and statistical plots according to '
        r'the selected data source; PCA also uses its stated data source.</p>', '', result.html
    )
    # 2026-09-24: normalization moved onto its own labelled line and a plot on
    # the unfiltered source now states the row counts instead of the filter
    # recipe. Both are wording checked by test_report_normalization_line; they
    # are removed here so the hashes keep proving the rest is unchanged.
    result.html = re.sub(r'<p><strong>Normalization:</strong>[^<]*</p>', '', result.html)
    result.html = re.sub(
        r'<p><strong>Filtering:</strong>[^<]*</p>', '<p><strong>Filtering:</strong></p>', result.html
    )
    # 2026-09-24: the PCA section states its parameters on a Projection line;
    # its wording is checked by test_report_pca_is_always_pca, so it is removed
    # here as the Normalization line is.
    result.html = re.sub(r'<p><strong>Projection:</strong>[^<]*</p>', '', result.html)
    key = mode + ':' + ','.join(kinds)
    actual = json.dumps([result.model_dump(), calls], sort_keys=True).encode()
    assert hashlib.sha256(actual).hexdigest() == SNAPSHOTS[key]


@pytest.mark.parametrize('mode', ['default', 'interactive'])
@pytest.mark.parametrize('scaling', ['centered', 'unit_variance', 'auto'])
def test_report_pca_forwards_selected_scaling(monkeypatch, mode, scaling):
    result, calls = render_case(monkeypatch, ('protein', 'phospho'), mode, pca_scaling=scaling)
    projections = [json.loads(call) for call in calls if json.loads(call)[0] in ('qc_pca_plot', 'qc_pca_interactive_html')]
    assert len(projections) == 2
    assert all(call[2]['scaling'] == scaling for call in projections)
    assert all(call[0] == ('qc_pca_interactive_html' if mode == 'interactive' else 'qc_pca_plot') for call in projections)
    assert not result.warnings


@pytest.mark.parametrize('mode', ['default', 'interactive'])
def test_report_retains_abundance_quantity_and_missingness(monkeypatch, mode):
    result, calls = render_case(monkeypatch, ('peptide', 'protein', 'phospho'), mode, selected_settings=True)
    parsed = [json.loads(call) for call in calls]
    abundance = [call for call in parsed if call[0].startswith('qc_abundance')]
    assert len(abundance) == 2
    for name, _, options in abundance:
        assert options['condition'] == 'B'
        assert name == ('qc_abundance_interactive_html' if mode == 'interactive' else 'qc_abundance_plot')
        assert ('dpi' in options) == (mode != 'interactive')
    missing = [call for call in parsed if call[0].startswith('completeness_missing_value_plot')]
    assert len(missing) == 3
    for name, _, options in missing:
        assert options['bin_count'] == 1
        assert options['header'] is False and options['text'] is False
        assert options['text_size'] == 12 and options['color'] == '#123456'
        assert (options['width_cm'], options['height_cm'], options['dpi']) == (25, 15, 144)
        assert options.get('quantity_column') == ('LFQ intensity' if name.endswith('_peptide') else None)
    coverage = next(call for call in parsed if call[0] == 'qc_peptide_coverage_plot')
    assert coverage[2]['quantity_column'] == 'LFQ intensity'
    assert not result.warnings


def test_selected_quantity_changes_real_missingness_bars_and_stale_selection_warns(monkeypatch):
    from app.services import completeness_tools, peptide_tools
    frame = pd.DataFrame({'File.Name': ['r1', 'r2', 'r1', 'r2'],
        'Stripped.Sequence': ['AAA', 'AAA', 'BBB', 'BBB'],
        'Precursor.Quantity': [1, 1, 1, 1], 'LFQ intensity': [1, 0, 0, 1]})
    monkeypatch.setattr(peptide_tools, 'get_peptide_frame', lambda: frame)
    monkeypatch.setattr(completeness_tools, '_peptide_sample_columns', lambda _: ['r1', 'r2'])
    seen = []
    def capture(fig, plt, **kwargs):
        ax = fig.axes[0]
        seen.append(([label.get_text() for label in ax.get_xticklabels()], [bar.get_height() for bar in ax.patches]))
        plt.close(fig)
        return b'png'
    monkeypatch.setattr(completeness_tools, '_to_png_bytes', capture)
    report.completeness_missing_value_plot_peptide(**report._missing_plot_options({'quantityColumn': 'LFQ intensity'}, peptide=True))
    assert seen[-1] == (['1'], [2])
    report.completeness_missing_value_plot_peptide()
    assert seen[-1] == (['0'], [2])
    warnings = []
    report._safe_png(renderer=lambda: report.completeness_missing_value_plot_peptide(quantity_column='Removed intensity'),
                     fallback_title='Missingness', warnings=warnings)
    assert len(warnings) == 1 and 'Removed intensity' in warnings[0]
    assert len(seen) == 2


@pytest.mark.parametrize('render_type', ['Normal', 'Interactive'])
def test_abundance_stale_condition_warns_without_expanding_scope(monkeypatch, render_type):
    from app.services import plot_images
    monkeypatch.setattr(plot_images, '_abundance_mean_intensities', lambda _: (
        pd.DataFrame({'GeneNames': ['A'], 'B': [2.]}), ['B'], 'Protein', 'GeneNames'))
    warnings = []
    result = report._abundance_report('protein', {'condition': 'Removed', 'type': render_type}, None, warnings, 'Abundance')
    assert len(warnings) == 1 and 'Removed' in warnings[0]
    assert 'Could not render' in result


@pytest.mark.parametrize('settings', [{'binCount': 1000000000}, {'widthCm': float('inf')}, {'dpi': 100000}, {'binCount': 1.5}])
def test_missing_report_settings_reject_unsafe_render_sizes(settings):
    with pytest.raises(ValueError):
        report._missing_plot_options(settings)
