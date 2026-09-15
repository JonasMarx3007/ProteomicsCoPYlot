from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from app.services import annotation_store, comparison_tools, data_tools, functions, single_protein_tools
from app.services.runtime_cache import invalidate_runtime_cache


def _frame(label: str, offset: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ProteinNames": [label],
            "GeneNames": [label],
            "s1": [offset + 1.0],
            "s2": [offset + 2.0],
            "s3": [offset + 3.0],
            "s4": [offset + 4.0],
            "s5": [offset + 5.0],
            "s6": [offset + 6.0],
        }
    )


@pytest.fixture
def source_annotation(monkeypatch: pytest.MonkeyPatch):
    invalidate_runtime_cache("visualization-source-test-start")
    metadata = pd.DataFrame(
        {
            "sample": ["s1", "s2", "s3", "s4", "s5", "s6"],
            "condition": ["A", "A", "A", "B", "B", "B"],
        }
    )
    annotation = SimpleNamespace(
        metadata=metadata,
        log2_data=_frame("DATA", 0.0),
        filtered_data=_frame("FILTERED", 10.0),
        imputed_data=_frame("IMPUTED", 20.0),
        imputation=SimpleNamespace(mode="quantile", applied=True),
    )
    monkeypatch.setattr(annotation_store, "get_annotation", lambda kind: annotation)
    monkeypatch.setattr(single_protein_tools, "get_annotation", lambda kind: annotation)
    monkeypatch.setattr(data_tools, "_get_current_frame", lambda kind: _frame("UPLOADED", 100.0))
    yield annotation
    invalidate_runtime_cache("visualization-source-test-end")


@pytest.mark.parametrize("sample_n", [True, False])
def test_boxplot_sample_counts_are_inline_and_optional(source_annotation, monkeypatch, sample_n):
    from app.api.routes_plots import single_protein_boxplot_route

    def capture(fig, plt, **kwargs):
        labels = [tick.get_text() for tick in fig.axes[0].get_xticklabels()]
        assert labels == (["A (n=3)", "B (n=3)"] if sample_n else ["A", "B"])
        plt.close(fig)
        return b"plot"

    monkeypatch.setattr(single_protein_tools, "_to_png_bytes", capture)
    response = single_protein_boxplot_route(
        kind="protein", protein="DATA", conditions='["B", "A"]', sampleN=sample_n,
    )
    assert response.body == b"plot"


def test_visualization_sources_are_explicit_and_never_substituted(source_annotation) -> None:
    expected = {
        "data": source_annotation.log2_data,
        "filtered": source_annotation.filtered_data,
        "imputed": source_annotation.imputed_data,
    }
    for requested, expected_frame in expected.items():
        source, frame, metadata = functions._visualization_data_source(
            "protein", data_source=requested
        )
        assert source == requested
        pd.testing.assert_frame_equal(frame, expected_frame)
        pd.testing.assert_frame_equal(metadata, source_annotation.metadata)


@pytest.mark.parametrize("identifier", ["workflow", "genes"])
@pytest.mark.parametrize("kind", ["protein", "phospho", "phosprot"])
@pytest.mark.parametrize("source,label", [(None, "DATA"), ("log2", "DATA"), ("filtered", "FILTERED"), ("imputed", "IMPUTED")])
def test_canvas_single_protein_tables_match_dedicated_defaults(source_annotation, identifier, kind, source, label):
    from app.services import analysis_functions
    workflow_column = {"protein": "ProteinNames", "phospho": "PTM_Collapse_key", "phosprot": "Phosphoprotein"}[kind]
    for name in ("log2_data", "filtered_data", "imputed_data"):
        frame = getattr(source_annotation, name)
        frame[workflow_column] = frame["ProteinNames"]
        frame["Gene_group"] = frame["GeneNames"]
    kwargs = dict(kind=kind, conditions=["B", "A"], identifier=identifier)
    selected = {"data_source": source} if source else {}
    box = analysis_functions.analysis_boxplot_table(protein=label, **selected, **kwargs)
    expected_box = single_protein_tools.single_protein_boxplot_table(protein=label, data_source=source or "log2", **kwargs)
    pd.testing.assert_frame_equal(box, expected_box)
    line = analysis_functions.analysis_lineplot_table(proteins=[label], **selected, **kwargs)
    expected_line = single_protein_tools.single_protein_lineplot_table(proteins=[label], data_source=source or "log2", **kwargs)
    pd.testing.assert_frame_equal(line, expected_line)
    assert not line.empty and set(line["Feature"]) == {label}


@pytest.mark.parametrize("source,test_type", [
    ("volcano", "unpaired"), ("volcano", "unpaired_welch"), ("volcano", "paired"),
    ("volcano_control", "unpaired_welch"), ("volcano_control", "paired"),
])
@pytest.mark.parametrize("raw", [False, True])
@pytest.mark.parametrize("kind,data_source", [("protein", "data"), ("protein", "imputed"), ("phospho", "data"), ("phospho", "imputed"), ("phosprot", "data")])
@pytest.mark.parametrize("identifier", ["workflow", "genes"])
def test_canvas_volcano_matches_dedicated_statistics(source_annotation, source, test_type, raw, kind, data_source, identifier):
    from app.services import analysis_functions, stats_tools
    from app.schemas.analysis import AnalysisVolcanoRequest
    from app.schemas.stats import VolcanoRequest, VolcanoControlRequest
    frame = pd.DataFrame({"ProteinNames": ["UP", "DOWN", "PARTIAL"], "GeneNames": ["GENE_UP", "GENE_DOWN", "GENE_PARTIAL"]})
    frame["PTM_Collapse_key"] = frame["ProteinNames"]
    frame["Phosphoprotein"] = frame["ProteinNames"]
    frame["Gene_group"] = frame["GeneNames"]
    samples = [f"{group}{rep}" for group in "ABCD" for rep in range(1, 4)]
    for index, sample in enumerate(samples):
        group, rep = divmod(index, 3)
        frame[sample] = [10 + group * 2 + rep * .3, 20 - group * 1.2 + rep * .4,
                         float("nan") if rep == 0 else 12 + group + rep * .2]
    source_annotation.filtered_data = frame
    source_annotation.imputed_data = frame.fillna(12.0).copy()
    for column in ("ProteinNames", "GeneNames", "PTM_Collapse_key", "Phosphoprotein", "Gene_group"):
        source_annotation.imputed_data[column] += "_IMPUTED"
    source_annotation.metadata = pd.DataFrame({"sample": samples, "condition": [s[0] for s in samples],
                                                "pair_id": [s[1:] for s in samples]})
    common = dict(kind=kind, dataSource=data_source, condition1="A", condition2="B", identifier=identifier,
                  testType=test_type, useUncorrected=raw, pValueThreshold=.05, log2fcThreshold=.5)
    if source == "volcano_control":
        common.update(condition1Control="C", condition2Control="D")
        expected = stats_tools.run_volcano_control(VolcanoControlRequest(**common))
    else:
        expected = stats_tools.run_volcano(VolcanoRequest(**common))
    actual = analysis_functions.analysis_volcano_data(AnalysisVolcanoRequest(source=source, **common))
    assert actual.points
    assert (actual.totalRows, actual.upregulatedCount, actual.downregulatedCount, actual.notSignificantCount) == (
        expected.totalRows, expected.upregulatedCount, expected.downregulatedCount, expected.notSignificantCount)
    rows = {str(row[expected.labelColumn]): row for row in expected.rows}
    assert set(rows) == {point.label for point in actual.points}
    for point in actual.points:
        row = rows[point.label]
        assert point.log2FC == row["log2FC"]
        assert point.negLog10P == row["neg_log10_adj_pval"]
        assert point.significance == row["significance"]
    assert actual.warnings == expected.warnings


def test_unavailable_imputation_fails_and_options_fall_back_to_data(
    source_annotation,
) -> None:
    source_annotation.imputation = SimpleNamespace(mode="none", applied=False)
    source_annotation.imputed_data = pd.DataFrame()

    with pytest.raises(ValueError, match="Run imputation successfully first"):
        functions._visualization_data_source("protein", data_source="imputed")

    comparison = comparison_tools.comparison_options("protein", data_source="imputed")
    single = single_protein_tools.single_protein_options(
        "protein", data_source="imputed"
    )
    assert comparison["dataSource"] == "data"
    assert comparison["imputedAvailable"] is False
    assert single["dataSource"] == "data"
    assert single["proteins"] == ["DATA"]
    assert single["imputedAvailable"] is False


def test_canvas_unavailable_imputation_never_substitutes_a_matrix(source_annotation):
    from app.services import analysis_functions
    from app.schemas.analysis import AnalysisVolcanoRequest
    source_annotation.imputation = SimpleNamespace(mode="none", applied=False)
    source_annotation.imputed_data = pd.DataFrame()
    for run in [
        lambda: analysis_functions.analysis_boxplot_table("protein", "DATA", ["A", "B"], data_source="imputed"),
        lambda: analysis_functions.analysis_lineplot_table("protein", ["DATA"], ["A", "B"], data_source="imputed"),
        lambda: analysis_functions.analysis_volcano_data(AnalysisVolcanoRequest(kind="protein", condition1="A", condition2="B", dataSource="imputed")),
    ]:
        with pytest.raises(ValueError):
            run()


@pytest.mark.parametrize("raw,expected", [
    ('["K0", "K1"]', ["K0", "K1"]),
    ('["feature,with,commas", "group;member"]', ["feature,with,commas", "group;member"]),
    ("K0,K1", ["K0", "K1"]), ("", []),
])
def test_canvas_selection_transport_matches_dedicated_plot_routes(raw, expected):
    from app.api import routes_analysis, routes_plots
    assert routes_analysis._csv_values(raw) == routes_plots._csv_values(raw) == expected


def test_canvas_selection_transport_rejects_non_string_json():
    from app.api import routes_analysis
    with pytest.raises(ValueError):
        routes_analysis._csv_values('["K0", 42]')


def test_comparison_and_single_protein_use_the_selected_matrix(source_annotation) -> None:
    data_options = single_protein_tools.single_protein_options(
        "protein", data_source="data"
    )
    filtered_options = single_protein_tools.single_protein_options(
        "protein", data_source="filtered"
    )
    imputed_options = single_protein_tools.single_protein_options(
        "protein", data_source="imputed"
    )

    assert data_options["proteins"] == ["DATA"]
    assert filtered_options["proteins"] == ["FILTERED"]
    assert imputed_options["proteins"] == ["IMPUTED"]
    assert imputed_options["filteredAvailable"] is True
    assert imputed_options["imputedAvailable"] is True

    table = single_protein_tools.single_protein_lineplot_table(
        "protein",
        ["FILTERED"],
        ["A", "B"],
        data_source="filtered",
    )
    assert table["Feature"].unique().tolist() == ["FILTERED"]
    assert table["Value"].tolist() == [11.0, 12.0, 13.0, 14.0, 15.0, 16.0]

    pearson = comparison_tools.pearson_correlation_table(
        "protein",
        sample1="s1",
        sample2="s2",
        data_source="imputed",
    )
    metrics = dict(zip(pearson["Metric"], pearson["Value"]))
    assert metrics["Points"] == 1
    left, right, _, _ = comparison_tools._pearson_vectors(
        "protein",
        "Single",
        sample1="s1",
        sample2="s2",
        data_source="imputed",
    )
    assert left.tolist() == [21.0]
    assert right.tolist() == [22.0]


@pytest.mark.parametrize("token", ["auto", "log2", "filtered", "imputed"])
def test_canonical_names_select_the_same_matrix_on_both_paths(
    source_annotation, token: str
) -> None:
    analysis_source, analysis_frame, _, _ = functions.analysis_data_source(
        "protein", data_source=token
    )
    visual_source, visual_frame, _ = functions._visualization_data_source(
        "protein", data_source=token
    )
    assert analysis_source == visual_source
    pd.testing.assert_frame_equal(analysis_frame, visual_frame)


def test_the_historical_alias_keeps_each_path_on_its_old_matrix(source_annotation) -> None:
    _, analysis_frame, _, _ = functions.analysis_data_source("protein", data_source="data")
    _, visual_frame, _ = functions._visualization_data_source("protein", data_source="data")

    pd.testing.assert_frame_equal(analysis_frame, source_annotation.filtered_data)
    pd.testing.assert_frame_equal(visual_frame, source_annotation.log2_data)


@pytest.mark.parametrize("token", ["nonsense", "raw", "log", "Filtered data"])
def test_unknown_tokens_are_rejected_rather_than_defaulted(token: str) -> None:
    with pytest.raises(ValueError, match="Unsupported data source"):
        functions.analysis_data_source("protein", data_source=token)
    with pytest.raises(ValueError, match="Unsupported data source"):
        functions._visualization_data_source("protein", data_source=token)


@pytest.mark.parametrize("token", ["", None, "  DATA  "])
def test_blank_and_padded_spellings_resolve_to_the_alias(source_annotation, token) -> None:
    _, analysis_frame, _, _ = functions.analysis_data_source("protein", data_source=token)
    _, visual_frame, _ = functions._visualization_data_source("protein", data_source=token)
    pd.testing.assert_frame_equal(analysis_frame, source_annotation.filtered_data)
    pd.testing.assert_frame_equal(visual_frame, source_annotation.log2_data)


def test_the_chat_layer_accepts_exactly_what_the_engine_accepts() -> None:
    from app.services.ai_functions import _AI_DATA_SOURCES
    from app.services.functions import DATA_SOURCE_CHOICES

    assert _AI_DATA_SOURCES == frozenset({"data", *DATA_SOURCE_CHOICES})


@pytest.mark.parametrize("token", ["auto", "log2", "filtered", "imputed"])
def test_an_explicit_matrix_is_never_silently_downgraded_in_chat(token: str) -> None:
    from app.services.ai_functions import _AI_DATA_SOURCES

    assert token in _AI_DATA_SOURCES, (
        f"chat coerces datasource={token} to the default matrix, so the answer "
        f"describes data the user did not ask about"
    )
