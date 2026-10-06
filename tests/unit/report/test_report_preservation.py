"""Pre-refactor report fingerprints; renderers are deterministic parameter probes."""
import hashlib
import html
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
# 2026-09-30: random seeds left the report text (imputation and k-means lines;
# checked by test_report_processing_provenance and test_report_pca_is_always_pca),
# the phospho coverage plots now receive the Phospho-specific page's own
# settings (include-ID, conditions, colours) and state the fixed Class I
# threshold. Those are the whole difference; verified by diffing the rendered
# HTML and renderer calls of every case against the previous code.
# 2026-10-05: the three `failure` cases moved, because warnings no longer go
# into the report: the "Report Warnings" section is gone, the failed figure's
# note no longer points to it, and a warning reads "<figure> could not be
# rendered: <reason>". Renderer calls are identical; those three edits are the
# whole HTML difference (diffed against the previous code). The rule is checked
# by test_error_disclosure.py.
SNAPSHOTS = {
    'qc_custom:': '31e9b3e4680befa02db2ec0566567663337d540546ff762cdaa8127b85e1d920',
    'qc_custom:protein': 'c5f49ff787b95e1bdc9933909b3ea9a2151bda1f9645619fbb7cf76c80efc83b',
    'qc_custom:phospho': '53dbbb98f87fc801c2e0e2bf77a217a68fbc000d14bc9c08772e560512f211f1',
    'qc_custom:peptide,protein,phospho': '3f4defb6e4f34704ee11906ffa7dedc4b5b4f0ccaa606b8126c0ffed70d41b8e',
    'qc_invalid:': '31e9b3e4680befa02db2ec0566567663337d540546ff762cdaa8127b85e1d920',
    'qc_invalid:protein': '40bd71e1d540cd50b498888d0faca10d330a28d56fedd45e09a780b63eb81ea6',
    'qc_invalid:phospho': '7be658abd2efbd6c27c683ca954254da2ff02b546f41f81ba4fedd3cdf56fea1',
    'qc_invalid:peptide,protein,phospho': '6de9ed6b0105b9c82bc41c759ca01e1e701d54bca129c6c2458dd4f400214f12',
    'default:': '31e9b3e4680befa02db2ec0566567663337d540546ff762cdaa8127b85e1d920',
    # The three `default` snapshots below changed when advanced mode stopped
    # gating the appearance settings: the case's custom PCA title now reaches
    # the PCA renderer with the panel closed, as it reaches the plot on screen.
    # That forwarded title is the whole difference.
    'default:protein': 'd0fda776c96dfb5484a2aba24633e5d019897aeca747c4dfcfed10a07f8f1f72',
    'default:phospho': '9fac7f7a4ed33fa3873d2edec98ae864189c2ec4e3a4f86d8379ca47c5363c39',
    'default:peptide,protein,phospho': '68d467416f74a84887400bfdee617c5e84c39ab7340f7975eb80d0a726b39470',
    'custom:': '31e9b3e4680befa02db2ec0566567663337d540546ff762cdaa8127b85e1d920',
    'custom:protein': '09c20fb17d34cd7e107b0d948535d272197c1bc2a56f495f3479a7e8c6b386ff',
    'custom:phospho': '4ae6cbc46e8433aff580b5fad7a9b5b5e3424709bb824bf5c991f7b1d518e243',
    'custom:peptide,protein,phospho': '58e2fcfb6915445f2340dc5312c3b7eae65eb1de63e3c481bb2a7d5e02467569',
    'interactive:': '31e9b3e4680befa02db2ec0566567663337d540546ff762cdaa8127b85e1d920',
    'interactive:protein': '30c6760a426e2b7e3fbb2eec64143a88d704b01d4c28af566c90660991da856e',
    'interactive:phospho': '3b81b5d19890afaece80d6a54b6f5e70b34c2c32b8bf47af45e3d91fa9ca353f',
    'interactive:peptide,protein,phospho': 'b81e3409f579fe9507eb307898681e9a0d449eb8fecbb68d83ea3206305fe771',
    'failure:': '31e9b3e4680befa02db2ec0566567663337d540546ff762cdaa8127b85e1d920',
    'failure:protein': '1994d4414c61395f46a39857b0f2699956a7fbdfe7cfbbc7947dbf49cbccf51b',
    'failure:phospho': '8edbbcba8c57435bde2c04ecb4a7a733bdef781e9bed06df1ebafe4c7ce27474',
    'failure:peptide,protein,phospho': '0ddec4eebf1941d1c4395d3ed998a6a7346b5825f26640990581d008ee6336f1',
}


def render_case(monkeypatch, kinds, mode, *, pca_scaling=None, selected_settings=False):
    monkeypatch.setattr(report, 'datetime', SimpleNamespace(now=lambda: datetime(2026, 9, 9)))
    comments = {key: [f'{key} <general> & text'] for key in report.GENERAL_COMMENTS}
    monkeypatch.setattr(report, 'GENERAL_COMMENTS', comments)
    monkeypatch.setattr(report, '_load_general_comments', lambda: comments)
    # 2026-09-30: the boxplot sections write their first sentences from the mode,
    # normalization and upload scale actually used; that wording is checked by
    # test_report_boxplot_text. The general comment is kept here so the hashes
    # keep proving the rest of the report is unchanged.
    monkeypatch.setattr(report, '_boxplot_comment_paragraphs',
                        lambda kind, mode, key: report.GENERAL_COMMENTS.get(key, []))
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
    # 2026-09-30: volcano blocks on imputed data state that imputed values were
    # tested as observations; the wording is checked by
    # test_imputed_value_counts, so it is removed here like the lines above.
    result.html = result.html.replace(
        '<p>' + html.escape(report.IMPUTED_AS_OBSERVED_SENTENCE) + '</p>', ''
    )
    # 2026-09-30: phosphosite sections state the session's localization
    # probability cutoff; the wording is checked by test_phospho_localization_cutoff.
    result.html = re.sub(r'<p><strong>Localization:</strong>[^<]*</p>', '', result.html)
    key = mode + ':' + ','.join(kinds)
    # Notebook availability is new response metadata, not a change to report contents.
    assert result.notebookToken is None and result.notebookError is None and result.notebookOmitted == []
    actual = json.dumps([result.model_dump(exclude={'notebookToken', 'notebookError', 'notebookOmitted'}), calls],
                        sort_keys=True).encode()
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
