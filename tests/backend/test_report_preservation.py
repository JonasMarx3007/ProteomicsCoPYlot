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
SNAPSHOTS = {
    'qc_custom:': 'bbfbb081d4e5687df47c4a524be5b3da7d3fa5ba63961b35f1fdc98c99f5ef3e',
    'qc_custom:protein': 'b17cd3ba228ad914d03757712b1514807887a918c8d998ce157fdfa8d5ec13a5',
    'qc_custom:phospho': '37202c75241d6f75ee6cc0d050107ddc192b3856cea1276fef8909882d62d94f',
    'qc_custom:peptide,protein,phospho': '8eee10ab12753b6994bbde5586e0a2f23dfd79e198292acedb1ea7600a3b8adf',
    'qc_invalid:': 'bbfbb081d4e5687df47c4a524be5b3da7d3fa5ba63961b35f1fdc98c99f5ef3e',
    'qc_invalid:protein': '330ae6f8e7fa09ff0e1a40fce2028c9c3f6f19abcf394ca8e03b8c5e9ab56e4c',
    'qc_invalid:phospho': 'f8bb8cd872a10097fc2d3aa33b170412d87d55c925bdeef0f956aec81beb6726',
    'qc_invalid:peptide,protein,phospho': '54c65acf3e6e5d67caea53acf569cb21937558d45c7dbae29458cd3a77e739da',
    'default:': 'bbfbb081d4e5687df47c4a524be5b3da7d3fa5ba63961b35f1fdc98c99f5ef3e',
    'default:protein': '9a1fb694a783396e87967dbedd13fa2e1c661735a9963e1d4ed1932dd8e4a299',
    'default:phospho': '1575ac1c55ce52756f2ca32b35757c02739c53e4dba479b070414555006aaa5b',
    'default:peptide,protein,phospho': 'c8364553dfdaf0fefd525eff8f98b6cb3632618fab8e2365316c5cd32bba8fd6',
    'custom:': 'bbfbb081d4e5687df47c4a524be5b3da7d3fa5ba63961b35f1fdc98c99f5ef3e',
    'custom:protein': '38df85bf0dc13c3479dd0e01430da4e40cc2e425c659888595acbdc35699b919',
    'custom:phospho': '5c9af4b13282e1463b30358d640b5f8f73e798bf30eb863733ba3e26f6aa2291',
    'custom:peptide,protein,phospho': '4cb8f259b30833c33003152cd621946c945a74c6170fab18930cbc826e0d50d3',
    'interactive:': 'bbfbb081d4e5687df47c4a524be5b3da7d3fa5ba63961b35f1fdc98c99f5ef3e',
    'interactive:protein': '248913b21f1a39f5a559bee887c32257e4298c054f8dce50c871ec10ef1d1727',
    'interactive:phospho': '23851e010528327dce905c1056c4b53abdeb964d03ee39233bbd82e0203caeb9',
    'interactive:peptide,protein,phospho': 'b252e8e17f38bd37e12060f64d7c7fc7d83cbc57e40dbdf91f3a907887fb4ada',
    'failure:': 'bbfbb081d4e5687df47c4a524be5b3da7d3fa5ba63961b35f1fdc98c99f5ef3e',
    'failure:protein': '8203b10b9593d813d5011d9961a60a903b1953ab6aef67e45fbc721121134e16',
    'failure:phospho': 'a7115146da8101cc122c57be07b21cc8916634158869eab041cfa7614744d668',
    'failure:peptide,protein,phospho': '3b2042645c73b45736c7b0cb87c96e73c22808366088ae181b48b2db1b7d2edf',
}


def render_case(monkeypatch, kinds, mode):
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
    settings = {} if mode == 'default' else {
        'type': 'Interactive' if mode == 'interactive' else 'Normal', 'dataSource': 'imputed',
        'header': False, 'legend': False, 'plotDim': '3D', 'method': 'UMAP', 'addEllipses': True,
        'dotSize': 90, 'clusterMethod': 'KMeans', 'clusterCount': 1, 'colorBy': 'Sample',
        'umapNNeighbors': 999, 'umapMinDist': -1, 'tsnePerplexity': 2000, 'tsneLearningRate': 1,
        'dbscanEps': 0, 'dbscanMinSamples': 999, 'randomState': 123, 'widthCm': 90, 'heightCm': 2, 'dpi': 50,
    }
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
    key = mode + ':' + ','.join(kinds)
    actual = json.dumps([result.model_dump(), calls], sort_keys=True).encode()
    assert hashlib.sha256(actual).hexdigest() == SNAPSHOTS[key]
