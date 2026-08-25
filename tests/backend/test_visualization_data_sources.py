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
