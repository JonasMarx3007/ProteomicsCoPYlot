"""Pre-refactor report fingerprints; renderers are deterministic parameter probes."""
import hashlib
import importlib
import json
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
# 2026-09-17: the report's version line is now derived from APP_VERSION rather
# than from a hand-maintained constant beside it. The string it prints is
# unchanged today, so these hashes did not move; they will move on the release
# that changes the application version, and that is the point of the change.
# 2026-09-21: the coverage plot's total line became a switch of its own
# (`referenceLine` in the coverage settings), so the report now forwards
# `reference_line=True` to the two coverage renderers. Reverting just that
# argument reproduces the previous hashes; it is the whole difference.
SNAPSHOTS = {
    'qc_custom:': '51b8f6856c2b611a19b9879bf620335be238d64f8d0926725a1272e4d735638e',
    'qc_custom:protein': 'c6c5cb984e0d4be84bad8fd5d5ecff646fef601190553fc05d0f69b6684e07d6',
    'qc_custom:phospho': '08038dd69d5cc0a0ccbdc9fb8dc6b3ad43808a7a65719af60ef436bb8b5bc04f',
    'qc_custom:peptide,protein,phospho': 'c9b3bcd836b222e52d9dd31446eebe157868724002b25c55afd430ac531cbb3b',
    'qc_invalid:': '51b8f6856c2b611a19b9879bf620335be238d64f8d0926725a1272e4d735638e',
    'qc_invalid:protein': 'b19fbf64dd73e59b4a7ec9a59c4652e585e627f303d9e2a2de4eb91d710e9258',
    'qc_invalid:phospho': 'c03c8d8b6c75f09779a56653a9d9bd521eb6e14f62a4e28b4725c5b5367a620f',
    'qc_invalid:peptide,protein,phospho': '1f4cee4f8057c2d5cfd5af0c54016ee9bd076d217290dae202afc56531551060',
    'default:': '51b8f6856c2b611a19b9879bf620335be238d64f8d0926725a1272e4d735638e',
    # The three `default` snapshots below changed when advanced mode stopped
    # gating the appearance settings: the case's custom PCA title now reaches
    # the PCA renderer with the panel closed, as it reaches the plot on screen.
    # That forwarded title is the whole difference.
    'default:protein': '0d7b12a96ad23e44f29a9e953c54c37c4ae8109737dc8db4df7838df641b0ced',
    'default:phospho': '56ef025baa8a779e62337655f313b9382b095e56245dc76d3c1c1590e092de1b',
    'default:peptide,protein,phospho': 'da1b29b4277de191111fea37c0fd416448f198e2e22a30b0eb434db4e78ae8dd',
    'custom:': '51b8f6856c2b611a19b9879bf620335be238d64f8d0926725a1272e4d735638e',
    'custom:protein': '68dfc320b90b50ce69285e4e61ef94506b46c194e7d3c48d56f32e0e4dd2f216',
    'custom:phospho': '5189d27a20d730826a7a54e131347a41badc3092322b8415b108691367b00e90',
    'custom:peptide,protein,phospho': '0a3cd239f7a54c723d78849ba251aede7fe5274aacfe5f2e84193b3d57a302cf',
    'interactive:': '51b8f6856c2b611a19b9879bf620335be238d64f8d0926725a1272e4d735638e',
    'interactive:protein': 'c35203e727c1327d570c5e373d2566176be41216c574ab37af30c90d53ff63f1',
    'interactive:phospho': '09a31f515434c0e04b9e3c5fa602e76a5ed215718251a38be31fd3dae9007b62',
    'interactive:peptide,protein,phospho': 'e4e49b6cd51b70cee6fa12deab630195e2888d8b34ecc18000da4ea9aa9b90e9',
    'failure:': '51b8f6856c2b611a19b9879bf620335be238d64f8d0926725a1272e4d735638e',
    'failure:protein': '3374964ac23d8915ad04fb61ceb62d976dd38c5c48a8603d812371ae20d75991',
    'failure:phospho': '8d568138e7dcaac30b734f86f86b38ff2ed2bf22e88fe6c423ae12dbf0409ce8',
    'failure:peptide,protein,phospho': '4d6268584101f534255dd285fe0df8647fb587f4a605f4c268cdc3566de891a3',
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
        'dbscanEps': 0, 'dbscanMinSamples': 999, 'randomState': 123, 'widthCm': 90, 'heightCm': 2, 'dpi': 50,
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
    result, calls = render_case(monkeypatch, kinds, mode)
    assert result.html.count(GENERATED_HTML_META) == 1
    # Only the newly added policy differs from the pre-hardening report baseline.
    result.html = result.html.replace('\n' + GENERATED_HTML_META, '', 1)
    # R7 intentionally changes only these sentences in this probe harness.
    # Their exact presence/meaning is checked by test_report_processing_provenance.
    # Removing them here proves all remaining HTML and renderer calls are unchanged.
    result.html = result.html.replace(
        '<p>QC plots use unfiltered, non-imputed data unless another data source is stated. '
        'Filtering and imputation apply to clustering and statistical plots according to '
        'the selected data source; PCA also uses its stated data source.</p>', ''
    ).replace('Not applied to this plot. Configured filtering: ', '')
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
