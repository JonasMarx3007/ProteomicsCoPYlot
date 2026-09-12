from __future__ import annotations

from pathlib import Path

import pytest

from app.schemas.chat import ChatMessage, OllamaChatRequest
from app.services import ai_functions
from app.services.ai_context_tools import build_module_context
from app.services.chat_tools import _DEFAULT_SYSTEM_PROMPT, _build_messages
from app.services.viewer_bootstrap import load_viewer_state


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module", autouse=True)
def load_example_project() -> None:
    result = load_viewer_state(ROOT / "viewer_config.json")
    assert not result.warnings


def context(
    module: str,
    workflow: str = "protein",
    mode: str | None = None,
    context_tier: str = "compact",
) -> str:
    return build_module_context(
        module,
        workflow_hint=workflow,
        mode_hint=mode,
        context_tier=context_tier,
    ).contextPrompt


def test_global_chat_policy_is_combined_with_module_context() -> None:
    request = OllamaChatRequest(
        message="Summarize this plot.",
        messages=[
            ChatMessage(role="system", content="MODULE EVIDENCE"),
            ChatMessage(role="user", content="Summarize this plot."),
        ],
    )
    _, messages = _build_messages(request)
    assert [message["role"] for message in messages] == ["system", "user"]
    assert messages[0]["content"].startswith(_DEFAULT_SYSTEM_PROMPT)
    assert messages[0]["content"].endswith("MODULE EVIDENCE")


def test_context_sanitizer_preserves_numeric_zero() -> None:
    assert ai_functions._safe_context_text(0) == "0"
    assert ai_functions._safe_context_text(0.0) == "0.0"


def test_coverage_context_exposes_final_extremes_without_recalculation() -> None:
    text = context("qc.coverage")
    assert "sample values are final computed counts: true" in text
    assert "highest sample: GRK_1; highest count: 7440" in text
    assert "lowest sample: GRK_5; lowest count: 7390" in text


def test_boxplot_and_cv_contexts_expose_bounded_comparisons() -> None:
    boxplot = context("qc.boxplot", mode="Mean")
    assert "comparison is descriptive: true" in boxplot
    assert "inferential test results: not available" in boxplot
    assert "report only numerical differences from available summary statistics" in boxplot
    assert "highest median condition: GRK; highest median: 8.05" in boxplot
    assert "lowest median condition: WT; lowest median: 8.02" in boxplot
    assert "median difference right minus left: 0.03" in boxplot
    assert "left iqr: 2.58; right iqr: 2.56" in boxplot
    assert "quality interpretation" not in boxplot
    assert "general warning signals" not in boxplot

    cv = context("qc.cv")
    assert "lower median cv means more consistent by this descriptive metric: true" in cv
    assert "lowest median cv condition: GRK; lowest median cv: 5.30" in cv
    assert "highest median cv condition: WT; highest median cv: 5.47" in cv
    assert "quality cutoff applied: false" in cv


def test_missingness_threshold_context_does_not_invent_outliers() -> None:
    text = context(
        "completeness.tables",
        mode="kind=protein|outlierThreshold=20|includeId=true",
    )
    assert "Direct answer evidence: threshold percent: 20; count: 0" in text
    assert "result: no samples exceed the threshold" in text
    assert "never call below threshold samples high or outliers" in text


def test_histogram_context_matches_condition_mean_distributions() -> None:
    text = context("qc.histogram")
    assert "Histogram Data: status: available; sample count: 10" in text
    assert "condition: WT; samples: 5; entity condition means: 7460" in text
    assert "condition: GRK; samples: 5; entity condition means: 7487" in text
    assert "normality not proven: true" in text
    assert "mean difference right minus left: 0.04" in text
    assert "when asked about normality or similarity report each condition mean median sd and skewness" in text


def test_pca_context_exposes_scores_and_bounded_geometry() -> None:
    compact = context("qc.pca", mode="method=PCA|plotDim=2D|type=Normal")
    standard = context(
        "qc.pca",
        mode="method=PCA|plotDim=2D|type=Normal",
        context_tier="standard",
    )
    text = context(
        "qc.pca",
        mode="method=PCA|plotDim=2D|type=Normal",
        context_tier="extended",
    )
    assert "Pca Variance: pc1: 49.65; pc2: 9.14; pc1 pc2 total: 58.79" in text
    assert compact.count("Pca Sample Score:") == 2
    assert standard.count("Pca Sample Score:") == 6
    assert text.count("Pca Sample Score:") == 10
    assert "centroid to within ratio: 4.44" in text
    assert "no universal clean separation cutoff is assumed" in text


def test_abundance_and_correlation_contexts_match_rendered_plot_inputs() -> None:
    abundance = context("qc.abundance")
    assert "condition: WT; rank: 1; identifier: H4_HUMAN; log10 mean intensity: 5.1512" in abundance
    assert "condition: GRK; rank: 1; identifier: H2A1B_HUMAN;H2A1D_HUMAN;H2A3_HUMAN" in abundance

    correlation = context("qc.correlation")
    assert "Correlation Data: status: available; sample count: 10; pair count: 45" in correlation
    assert "lowest pair: WT_5_vs_GRK_1" in correlation
    assert "group median comparison: within condition median is higher" in correlation


def test_pca_context_and_report_use_selected_scaling(monkeypatch):
    import importlib
    import numpy as np
    import pandas as pd
    from app.services import plot_images

    report = importlib.import_module('app.services.report_function')
    samples = ['s1', 's2', 's3', 's4']
    frame = pd.DataFrame([[0, 100, 200, 300], [0, 1, 0, 1], [1, 0, 1, 0]], columns=samples)
    meta = pd.DataFrame({'sample': samples, 'condition': ['A', 'A', 'B', 'B']})
    monkeypatch.setattr(plot_images, 'analysis_data_source', lambda *a, **k: (None, frame, None, None))
    monkeypatch.setattr(plot_images, '_get_sample_columns', lambda *a: samples)
    monkeypatch.setattr(plot_images, '_metadata_for_kind', lambda *a: meta)
    projection = plot_images._pca_projection
    captured = []

    def capture(*args, **kwargs):
        result = projection(*args, **kwargs)
        captured.append((kwargs, result[1]))
        return result

    monkeypatch.setattr(plot_images, '_pca_projection', capture)
    for scaling, expected_pc1 in [('unit_variance', 76.87419249), ('centered', 99.99680015)]:
        options = report._pca_plot_options({'scaling': scaling})
        _, report_variance, _ = projection('protein', scaling=options['scaling'])
        text = context('qc.pca', mode=f'method=PCA|plotDim=2D|dataSource=data|scaling={scaling}')
        assert captured[-1][0]['scaling'] == scaling
        np.testing.assert_allclose(captured[-1][1], report_variance)
        assert report_variance[0] == pytest.approx(expected_pc1)
        assert f'pc1: {expected_pc1:.2f}' in text


def test_abundance_context_respects_condition_and_rejects_stale_selection():
    text = context('qc.abundance', mode='condition=WT')
    assert 'condition: WT; rank: 1' in text
    assert 'condition: GRK; rank:' not in text
    stale = context('qc.abundance', mode='condition=missing%7Ccondition')
    assert 'status: unavailable' in stale
    assert 'Abundance Top Entity:' not in stale


def test_literal_selection_transport_matches_plot_table_and_context(monkeypatch):
    import json
    import pandas as pd
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api import routes_plots
    from app.services import single_protein_tools
    names = ['P1;P2', 'Drug, high', 'A|B=δ', '100% ready', 'quote"name']
    seen = []
    def plot(**kwargs):
        seen.append((kwargs['proteins'], kwargs['conditions']))
        return b'png'
    def table(kind, proteins, conditions, **kwargs):
        seen.append((proteins, conditions))
        return pd.DataFrame({'Identifier': proteins})
    monkeypatch.setattr(routes_plots, 'single_protein_lineplot_plot', plot)
    monkeypatch.setattr(routes_plots, 'single_protein_lineplot_table', table)
    monkeypatch.setattr(single_protein_tools, 'single_protein_lineplot_table', table)
    query = {'proteins': json.dumps(names), 'conditions': json.dumps(names)}
    with TestClient(app) as client:
        image = client.get('/api/plots/single-protein/protein/lineplot.png', params=query)
        exported = client.get('/api/plots/single-protein/protein/lineplot-table', params=query)
    assert image.status_code == exported.status_code == 200
    assert image.content == b'png'
    assert [row['Identifier'] for row in exported.json()['rows']] == names
    mode = json.dumps({'proteins': names, 'conditions': names, 'kind': 'protein'})
    ai_functions.single_protein_lineplot(mode=mode)
    assert seen == [(names, names)] * 3
    assert ai_functions._parse_mode_pairs(json.dumps({'protein': 'P1;P2|δ', 'header': 'false'}))['protein'] == 'P1;P2|δ'


@pytest.mark.parametrize('raw', ['[1]', '[null]', '[["nested"]]', '[broken'])
def test_malformed_selection_arrays_are_not_reinterpreted_as_names(raw):
    from app.services.functions import parse_selection_list
    with pytest.raises(ValueError):
        parse_selection_list(raw)


@pytest.mark.parametrize('path,renderer,extra', [
    ('/api/plots/stats/protein/pathway-heatmap.png', 'pathway_heatmap_png', {'pathway': 'Path|δ, test'}),
    ('/api/plots/single-protein/phospho/heatmap.png', 'single_protein_heatmap_plot', {'protein': 'P1;P2|δ'}),
    ('/api/plots/single-protein/protein/boxplot.png', 'single_protein_boxplot_plot', {'protein': 'P1;P2|δ'}),
    ('/api/plots/phospho/coverage.png', 'phospho_coverage_png', {}),
])
def test_condition_selection_arrays_reach_other_plot_families(monkeypatch, path, renderer, extra):
    import json
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api import routes_plots
    names = ['Drug, high', 'A;B|δ', 'x=y']
    seen = []
    def render(**kwargs):
        seen.append(kwargs)
        return b'png'
    monkeypatch.setattr(routes_plots, renderer, render)
    with TestClient(app) as client:
        response = client.get(path, params={**extra, 'conditions': json.dumps(names)})
        assert response.status_code == 200
        invalid = client.get(path, params={**extra, 'conditions': '[1]'})
        assert invalid.status_code == 400
    assert seen[0]['conditions'] == names
    assert all(seen[0][key] == value for key, value in extra.items())
    assert len(seen) == 1


def test_selection_transport_retains_legacy_contracts():
    from app.services.functions import parse_selection_list
    assert parse_selection_list('A,B;C') == ['A', 'B;C']
    assert ai_functions._split_mode_list('A,B;C') == ['A', 'B', 'C']
    assert ai_functions._parse_mode_pairs('protein=P1|header=false') == {'protein': 'P1', 'header': 'false'}


@pytest.mark.parametrize('level,quantity,expected', [
    ('peptide', 'Precursor.Quantity', 1), ('precursor', 'Precursor.Quantity', 2),
    ('peptide', 'LFQ intensity', 1), ('precursor', 'LFQ intensity', 1),
])
def test_peptide_coverage_context_matches_plot_and_selected_input(monkeypatch, level, quantity, expected):
    import pandas as pd
    from urllib.parse import quote
    from app.services import peptide_tools, plot_images

    frame = pd.DataFrame({'File.Name': ['ctrl_01.raw'] * 4 + ['treat_01.raw'] * 4,
        'Stripped.Sequence': ['AAA', 'AAA', 'BBB', 'CCC'] * 2,
        'Precursor.Id': ['AAA2', 'AAA3', 'BBB2', 'CCC2'] * 2,
        'Precursor.Quantity': [10, 20, 0, None, 10, 10, 10, 10],
        'LFQ intensity': [0, 0, 30, None, 10, 10, 10, 10]})
    meta = pd.DataFrame({'sample': ['ctrl_01.raw'], 'label': ['C_1'], 'condition': ['C']})
    monkeypatch.setattr(peptide_tools, 'get_peptide_frame', lambda: frame)
    monkeypatch.setattr(plot_images, '_peptide_coverage_metadata', lambda *a, **k: meta)
    rows, total = ai_functions._coverage_rows_from_peptide(quantity_column=quantity, level=level)
    assert rows['Count'].tolist() == [expected]
    assert rows['Condition'].tolist() == ['C']
    def inspect(fig, plt, **kwargs):
        try:
            assert [bar.get_height() for bar in fig.axes[0].patches] == [expected]
            assert list(fig.axes[0].lines[0].get_ydata()) == [total, total]
        finally:
            plt.close(fig)
        return b'png'
    monkeypatch.setattr(plot_images, '_to_png_bytes', inspect)
    assert plot_images.qc_peptide_coverage_plot(quantity_column=quantity, level=level) == b'png'
    text = context('qc.coverage', workflow='peptide', mode=f'level={level}|quantityColumn={quote(quantity)}')
    assert f'entity: {level}s' in text
    assert f'count: {expected}' in text
    assert 'samples: 1' in text
    invalid = context('qc.coverage', workflow='peptide', mode=f'level={level}|quantityColumn=Removed')
    assert 'unavailable' in invalid


def test_missing_heatmap_context_distinguishes_aggregates_from_visual_patterns() -> None:
    text = context("completeness.heatmap", mode="kind=protein")
    assert "Missing Heatmap Data: status: available" in text
    assert "sample summaries support column level comparisons" in text
    assert "specific row or block patterns require the rendered heatmap or row level matrix" in text


def test_general_context_exposes_active_project_state_without_machine_delimiters() -> None:
    text = context("data.upload")
    assert "Project State: active dataset package: HEK293" in text
    assert "Project Dataset: kind: protein; status: loaded" in text
    assert "annotation: available" in text
    assert "samples: 10; conditions: 2" in text
    assert "|" not in text


def test_volcano_context_is_rank_limited_and_uses_informative_significance_values() -> None:
    text = context(
        "stats.volcano",
        mode=(
            "source=volcano|kind=protein|dataSource=data|condition1=WT|condition2=GRK|"
            "identifier=workflow|testType=unpaired|pValueThreshold=0.05|"
            "log2fcThreshold=1|useUncorrected=false"
        ),
    )
    assert "max per group: 2" in text
    assert text.count("Volcano Term:") == 4
    assert "term: CCN1_HUMAN; log2fc: 2.75; selected p value: 2.588e-07" in text
    assert "term: NFM_HUMAN; log2fc: -1.00; selected p value: 3.942e-08" in text
    assert "do not replace small p values with rounded zero" in text
    assert "|" not in text


@pytest.mark.parametrize(
    ("test_type", "description", "is_paired"),
    [
        ("unpaired", "unpaired_student_t_test_with_pooled_variance", False),
        ("unpaired_welch", "unpaired_welch_t_test_with_unequal_variance", False),
        ("paired", "paired_student_t_test_on_within_pair_differences", True),
    ],
)
def test_all_ai_statistical_contexts_preserve_the_selected_test_type(
    test_type: str,
    description: str,
    is_paired: bool,
) -> None:
    volcano = ai_functions.stats_volcano_plot(
        mode=f"source=volcano_control|testType={test_type}"
    )["summary"]
    ora = ai_functions.stats_ora_plot(
        mode=f"source=volcano_control|testType={test_type}"
    )["summary"]
    phosprot = ai_functions.phospho_phosprot_regulation_plot(
        mode=f"testType={test_type}"
    )["summary"]

    for payload in (volcano, ora, phosprot):
        assert f"test_type={test_type}" in payload
        assert f"selected_test={test_type}" in payload
    assert f"selected_test_description={description}" in phosprot
    control_description = (
        "paired_experimental_differences_with_propagated_control_variance"
        if is_paired else "unpaired_propagated_variance_with_satterthwaite_degrees_of_freedom"
    )
    for payload in (volcano, ora):
        assert f"selected_test_description={control_description}" in payload
    assert "_minus_(mean_condition2_control_minus_mean_condition1_control)" in volcano

    assert ("volcano_pairing|" in volcano) is is_paired
    assert "supported_tests=unpaired,unpaired_welch,paired" in volcano


def test_ai_statistical_context_uses_safe_default_for_unknown_test_type() -> None:
    assert ai_functions._normalize_stats_test_type("not-a-test") == "unpaired"
