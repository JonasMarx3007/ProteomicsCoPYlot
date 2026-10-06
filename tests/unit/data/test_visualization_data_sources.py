from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from app.services import annotation_store, comparison_tools, data_tools, functions, single_protein_tools
from app.services.functions import DATA_SOURCES
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
    # metadata_for_kind lives in data_tools since 2026-09-25 and reads its store.
    monkeypatch.setattr(data_tools, "get_annotation", lambda kind: annotation)
    monkeypatch.setattr(data_tools, "_get_current_frame", lambda kind: _frame("UPLOADED", 100.0))
    yield annotation
    invalidate_runtime_cache("visualization-source-test-end")


@pytest.fixture
def boxplot_project():
    """One protein with a missing value in condition A, stored the way an upload is.

    tests/conftest.py restores the stores after this module.
    """
    import numpy as np

    from app.schemas.annotation import AnnotationFilterConfig
    from app.services.annotation_store import reset_all_annotations, save_annotation
    from app.services.dataset_store import reset_all_datasets, save_table_dataset

    reset_all_datasets()
    reset_all_annotations()
    samples = [f"s{index}" for index in range(1, 7)]
    frame = pd.DataFrame({"ProteinNames": ["DATA", "OTHER"], "GeneNames": ["DATA", "OTHER"],
                          **{sample: [float(index), float(index) + 1] for index, sample in enumerate(samples)}})
    frame.loc[0, "s2"] = np.nan
    save_table_dataset("boxplot.tsv", "protein", frame)
    save_annotation(kind="protein", source_data=frame, log2_data=frame, filtered_data=frame,
                    metadata=pd.DataFrame({"sample": samples, "condition": list("AAABBB")}),
                    is_log2_transformed=True, metadata_source="manual", filter_config=AnnotationFilterConfig(),
                    auto_detected=False, warnings=[])
    yield
    reset_all_datasets()
    reset_all_annotations()


@pytest.mark.parametrize("sample_n", [True, False])
def test_boxplot_sample_counts_are_inline_and_optional(boxplot_project, monkeypatch, sample_n):
    """The count of measured values sits in each condition label, and can be switched off.

    The real route draws the figure; the renderer's own save step is wrapped only
    to read the tick labels before the figure is written out. Condition A has a
    missing value, so its n is 2 and not the 3 samples it holds.
    """
    import json

    from fastapi.testclient import TestClient

    from app.main import app
    from app.services.notebook_single import box_module

    module = box_module()
    save = module.to_png_bytes
    labels: list[list[str]] = []

    def read_labels(fig, plt, **kwargs):
        labels.append([tick.get_text() for tick in fig.axes[0].get_xticklabels()])
        return save(fig, plt, **kwargs)

    monkeypatch.setattr(module, "to_png_bytes", read_labels)
    with TestClient(app) as client:
        response = client.get("/api/plots/single-protein/protein/boxplot.png",
                              params={"protein": "DATA", "conditions": json.dumps(["B", "A"]), "sampleN": sample_n})
    assert response.status_code == 200, response.text[:300]
    assert response.content.startswith(b"\x89PNG")
    assert response.headers.get("x-copylot-notebook")
    assert labels == [["A (n=2)", "B (n=3)"] if sample_n else ["A", "B"]]


def test_visualization_sources_are_explicit_and_never_substituted(source_annotation) -> None:
    expected = {
        "data": source_annotation.log2_data,
        "filtered": source_annotation.filtered_data,
        "imputed": source_annotation.imputed_data,
    }
    for requested, expected_frame in expected.items():
        source, frame, metadata = functions.select_matrix(
            "protein", data_source=requested
        )
        assert source == requested
        pd.testing.assert_frame_equal(frame, expected_frame)
        pd.testing.assert_frame_equal(metadata, source_annotation.metadata)


@pytest.mark.parametrize("identifier", ["workflow", "genes"])
@pytest.mark.parametrize("kind", ["protein", "phospho", "phosprot"])
@pytest.mark.parametrize("source,label", [(None, "DATA"), ("data", "DATA"), ("filtered", "FILTERED"), ("imputed", "IMPUTED")])
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
    expected_box = single_protein_tools.single_protein_boxplot_table(protein=label, data_source=source or "data", **kwargs)
    pd.testing.assert_frame_equal(box, expected_box)
    line = analysis_functions.analysis_lineplot_table(proteins=[label], **selected, **kwargs)
    expected_line = single_protein_tools.single_protein_lineplot_table(proteins=[label], data_source=source or "data", **kwargs)
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
    # "data" is the unfiltered annotated matrix, so it needs the same samples.
    # Under the old two-resolver world "data" reached the filtered frame, so
    # this fixture never had to set log2_data at all.
    source_annotation.log2_data = frame
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
        assert point.negLog10P == row["neg_log10_selected_pval"]
        assert point.significance == row["significance"]
    assert actual.warnings == expected.warnings


def test_unavailable_imputation_fails_and_options_fall_back_to_data(
    source_annotation,
) -> None:
    source_annotation.imputation = SimpleNamespace(mode="none", applied=False)
    source_annotation.imputed_data = pd.DataFrame()

    with pytest.raises(ValueError, match="Run imputation successfully first"):
        functions.select_matrix("protein", data_source="imputed")

    comparison = comparison_tools.comparison_options("protein")
    single = single_protein_tools.single_protein_options(
        "protein", data_source="imputed"
    )
    assert comparison["dataSource"] == "data", "comparison is QC: always the loaded data"
    assert single["dataSource"] == "data"
    assert single["proteins"] == ["DATA"]
    assert "imputed" not in single["availableDataSources"]
    assert single["defaultDataSource"] == "filtered", "the ladder drops to what exists"


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
def test_the_plot_routes_read_selections_one_way(raw, expected):
    # 2026-10-02: the /api/analysis boxplot and lineplot routes this was compared
    # with were removed (no page called them); the canvas uses these routes.
    from app.api import routes_plots
    from app.services.functions import parse_selection_list
    assert routes_plots._csv_values(raw) == parse_selection_list(raw) == expected


def test_the_plot_routes_reject_non_string_json():
    from app.api import routes_plots
    with pytest.raises(ValueError):
        routes_plots._csv_values('["K0", 42]')


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
    assert imputed_options["availableDataSources"] == ["data", "filtered", "imputed"]
    assert imputed_options["defaultDataSource"] == "imputed", "the ladder opens on the most processed"

    table = single_protein_tools.single_protein_lineplot_table(
        "protein",
        ["FILTERED"],
        ["A", "B"],
        data_source="filtered",
    )
    assert table["Feature"].unique().tolist() == ["FILTERED"]
    assert table["Value"].tolist() == [11.0, 12.0, 13.0, 14.0, 15.0, 16.0]

    # Comparison is QC now: it reads the loaded data and cannot be pointed
    # elsewhere, so a Venn still has the missingness it exists to compare.
    left, right, _, _ = comparison_tools._pearson_vectors(
        "protein", "Single", sample1="s1", sample2="s2",
    )
    assert left.tolist() == [1.0], "comparison must read the loaded matrix"
    assert right.tolist() == [2.0]


@pytest.mark.parametrize("token", DATA_SOURCES)
def test_every_name_selects_exactly_one_matrix(source_annotation, token: str) -> None:
    """One vocabulary, one matrix each, on every path.

    There used to be two resolvers, and `"data"` meant the filtered matrix on
    one and the unfiltered one on the other -- so the same request returned
    7,450 rows through the statistics path and 7,490 through the visualization
    path, with nothing in the response to say which.
    """
    expected = {
        "data": source_annotation.log2_data,
        "filtered": source_annotation.filtered_data,
        "imputed": source_annotation.imputed_data,
    }[token]
    source, frame, _ = functions.select_matrix("protein", token)
    assert source == token
    pd.testing.assert_frame_equal(frame, expected)


def test_data_is_the_unfiltered_annotated_matrix(source_annotation) -> None:
    """The word that used to mean two things."""
    _, frame, _ = functions.select_matrix("protein", "data")
    pd.testing.assert_frame_equal(frame, source_annotation.log2_data)
    assert not frame.equals(source_annotation.filtered_data)


@pytest.mark.parametrize("token", ["nonsense", "raw", "log", "log2", "auto", "Filtered data"])
def test_unknown_tokens_are_rejected_rather_than_defaulted(token: str) -> None:
    """Including the two names that used to work: they were the ambiguity."""
    with pytest.raises(ValueError, match="Unsupported data source"):
        functions.select_matrix("protein", token)


@pytest.mark.parametrize("token", ["", None, "  DATA  "])
def test_blank_and_padded_spellings_mean_the_unfiltered_matrix(source_annotation, token) -> None:
    _, frame, _ = functions.select_matrix("protein", token)
    pd.testing.assert_frame_equal(frame, source_annotation.log2_data)


def test_the_ladder_offers_the_most_processed_matrix_that_exists(source_annotation) -> None:
    """What a fresh panel opens on: imputed > filtered > data."""
    assert functions.most_processed_data_source("protein") == "imputed"
    source_annotation.imputation = SimpleNamespace(mode="none", applied=False)
    source_annotation.imputed_data = pd.DataFrame()
    assert functions.most_processed_data_source("protein") == "filtered"
    source_annotation.filtered_data = pd.DataFrame()
    assert functions.most_processed_data_source("protein") == "data"


def test_availability_matches_what_can_actually_be_selected(source_annotation) -> None:
    """A source is offered only when choosing it would work."""
    for token, available in functions.data_source_availability("protein").items():
        if available:
            functions.select_matrix("protein", token)
        else:
            with pytest.raises(ValueError):
                functions.select_matrix("protein", token)


def test_the_chat_layer_accepts_exactly_what_the_engine_accepts() -> None:
    from app.services.ai_functions import _AI_DATA_SOURCES

    assert _AI_DATA_SOURCES == frozenset(DATA_SOURCES)


@pytest.mark.parametrize("token", DATA_SOURCES)
def test_an_explicit_matrix_is_never_silently_downgraded_in_chat(token: str) -> None:
    from app.services.ai_functions import _AI_DATA_SOURCES

    assert token in _AI_DATA_SOURCES, (
        f"chat coerces datasource={token} to the default matrix, so the answer "
        f"describes data the user did not ask about"
    )
