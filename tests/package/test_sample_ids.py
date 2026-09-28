from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from proteomicscopylot.notebook_functions import (
    extract_id_or_number,
    paired_sample_columns as notebook_paired_sample_columns,
    volcano_data_f,
)
from app.services.functions import (
    extract_sample_id,
    paired_sample_columns as backend_paired_sample_columns,
)


@pytest.mark.parametrize(
    ("sample_name", "expected"),
    [
        (
            "[1] 20250725_nElute_tims1_JM_Mrowka_WP_01_Slot1-61_1_11156"
            ".htrms.PG.Log2Quantity",
            "11156",
        ),
        (
            "[1] 20250725_nElute_tims1_JM_Mrowka_WP_01_Slot1-61_1_11156.htrms",
            "11156",
        ),
        (
            r"Z:\Mario\example\20250131_nElute_tims1_MMu_A1D_Slot1-01_1_9790.d",
            "9790",
        ),
        ("sample_2.d.PG.Log2Quantity", "2"),
        ("sample_2.htrms", "2"),
        ("sample_00042.d.PG.AvgLog2Quantity", "00042"),
        ("sample_00042.d.PG.Quantity", "00042"),
        ("sample_00042.d.PG.Normalised", "00042"),
        ("sample_00042.d.EG.TotalQuantity", "00042"),
        ("sample_00042.d.PG.MaxLFQ", "00042"),
        ("sample_00042.htrms.Precursor.Normalised", "00042"),
        ("sample_00042 MaxLFQ Intensity", "00042"),
        ("sample_00042 MaxLFQ Unique Intensity", "00042"),
        ("sample_00042 Total Spectral Count", "00042"),
        ("sample_00042 MS2 Count", "00042"),
        ("Intensity 01", "01"),
        ("LFQ intensity 0002", "0002"),
        ("sample_without_an_identifier.raw", "sample_without_an_identifier.raw"),
    ],
)
def test_extract_sample_id_across_supported_export_styles(
    sample_name: str,
    expected: str,
) -> None:
    assert extract_sample_id(sample_name) == expected
    assert extract_id_or_number(sample_name) == expected


def test_canonical_example_headers_extract_real_ids() -> None:
    frame = pd.read_csv(
        "proteomicscopylot/example_data/"
        "20260511_144120_20240822_JM_HEK293_WP_Report_PG.tsv",
        sep="\t",
        nrows=0,
    )
    sample_columns = [column for column in frame.columns if ".PG.Log2Quantity" in column]
    assert [extract_sample_id(column) for column in sample_columns] == [
        "8070",
        "8071",
        "8072",
        "8073",
        "8074",
        "8064",
        "8065",
        "8066",
        "8067",
        "8068",
    ]


def test_backend_services_share_the_canonical_extractor() -> None:
    from app.services.completeness_tools import _extract_id_or_number as completeness
    from app.services.peptide_tools import _extract_id_or_number as peptide
    from app.services.phospho_tools import _extract_id_or_number as phospho
    from app.services.plot_images import _extract_id_or_number as plots
    from app.services.single_protein_tools import _extract_id_or_number as single_protein
    from app.services.stats_tools import _extract_id_or_number as stats
    from app.services.table_functions import _extract_id_or_number as tables

    extractors = [completeness, peptide, phospho, plots, single_protein, stats, tables]
    assert all(extractor is extract_sample_id for extractor in extractors)


def paired_metadata() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "sample": ["before_c", "before_a", "before_d", "before_b",
                       "after_d", "after_a", "after_c", "after_b"],
            "condition": ["before"] * 4 + ["after"] * 4,
            "pair_id": ["C", "A", "D", "B", "D", "A", "C", "B"],
        }
    )


def paired_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ProteinNames": [
                "varied",
                "zero difference",
                "constant difference",
                "numeric zero",
            ],
            "before_a": [1.0, 1.0, 1.0, 0.0],
            "before_b": [10.0, 2.0, 2.0, 1.0],
            "before_c": [100.0, 3.0, 3.0, 2.0],
            "before_d": [1000.0, 4.0, 4.0, 3.0],
            "after_a": [3.0, 1.0, 3.0, 1.0],
            "after_b": [14.0, 2.0, 4.0, 2.0],
            "after_c": [np.nan, 3.0, 5.0, 3.0],
            "after_d": [1009.0, 4.0, 6.0, 4.0],
        }
    )


def test_pair_columns_use_explicit_identity_and_condition1_order() -> None:
    metadata = paired_metadata()
    expected = (
        ["before_c", "before_a", "before_d", "before_b"],
        ["after_c", "after_a", "after_d", "after_b"],
    )
    assert backend_paired_sample_columns(metadata, "before", "after") == expected
    assert notebook_paired_sample_columns(metadata, "before", "after") == expected


def test_pair_columns_exclude_unmatched_samples_and_allow_unequal_groups() -> None:
    metadata = pd.DataFrame(
        {
            "sample": ["before_c", "before_a", "before_b", "before_unpaired",
                       "after_b", "after_d", "after_a"],
            "condition": ["before"] * 4 + ["after"] * 3,
            "pair_id": ["C", "A", "B", "", "B", "D", "A"],
        }
    )
    expected = (
        ["before_a", "before_b"],
        ["after_a", "after_b"],
    )
    assert backend_paired_sample_columns(metadata, "before", "after") == expected
    assert notebook_paired_sample_columns(metadata, "before", "after") == expected


@pytest.mark.parametrize(
    ("metadata", "message"),
    [
        (
            pd.DataFrame(
                {
                    "sample": ["control_mouse7_run1", "treated_mouse9_run1"],
                    "condition": ["before", "after"],
                }
            ),
            "pair_id",
        ),
        (
            pd.DataFrame(
                {
                    "sample": ["a1", "a2", "b1", "b2"],
                    "condition": ["before", "before", "after", "after"],
                    "pair_id": ["A", "A", "A", "B"],
                }
            ),
            "unique pair IDs",
        ),
        (
            pd.DataFrame(
                {
                    "sample": ["a1", "a2", "b1", "b2"],
                    "condition": ["before", "before", "after", "after"],
                    "pair_id": ["A", "B", "A", ""],
                }
            ),
            "at least two matched pair IDs",
        ),
        (
            pd.DataFrame(
                {
                    "sample": ["a1", "a2", "b1", "b2"],
                    "condition": ["before", "before", "after", "after"],
                    "pair_id": ["A", "B", "A", "C"],
                }
            ),
            "at least two matched pair IDs",
        ),
    ],
)
def test_invalid_pair_metadata_is_rejected(metadata: pd.DataFrame, message: str) -> None:
    for resolver in (backend_paired_sample_columns, notebook_paired_sample_columns):
        with pytest.raises(ValueError, match=message):
            resolver(metadata, "before", "after")


def test_backend_and_notebook_paired_statistics_match_identity_and_missingness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import stats_tools

    frame = paired_frame()
    metadata = paired_metadata()
    notebook_result = volcano_data_f(
        frame,
        metadata,
        "before",
        "after",
        workflow="Protein",
        paired="paired",
        uncorrected=True,
    )

    monkeypatch.setattr(
        stats_tools,
        "_stats_source",
        lambda *_args, **_kwargs: ("data", frame.copy(), metadata.copy(), []),
    )
    _, _, backend_result, _ = stats_tools._volcano_dataframe(
        kind="protein",
        condition1="before",
        condition2="after",
        identifier="workflow",
        p_value_threshold=0.05,
        log2fc_threshold=1.0,
        test_type="paired",
        use_uncorrected=True,
        data_source="data",
    )

    columns = ["log2FC", "pval", "n_pairs"]
    np.testing.assert_allclose(
        backend_result[columns].to_numpy(dtype=float),
        notebook_result[columns].to_numpy(dtype=float),
    )
    assert notebook_result["n_pairs"].tolist() == [3, 4, 4, 4]
    assert notebook_result["log2FC"].tolist() == [-5.0, 0.0, -2.0, -1.0]
    assert np.isnan(notebook_result["pval"].iloc[1])
    assert notebook_result["pval"].iloc[2] == 0.0

    reordered = metadata.sample(frac=1, random_state=7).reset_index(drop=True)
    reordered_result = volcano_data_f(
        frame,
        reordered,
        "before",
        "after",
        workflow="Protein",
        paired="Paired",
        uncorrected=True,
    )
    np.testing.assert_allclose(
        reordered_result[columns].to_numpy(dtype=float),
        notebook_result[columns].to_numpy(dtype=float),
    )


def test_pair_id_survives_uploaded_and_combined_metadata() -> None:
    from app.services.annotation_processor import normalize_uploaded_metadata
    from app.services.metadata_upload_store import build_combined_metadata_frame

    data = pd.DataFrame(columns=["sample_a", "sample_b"])
    first = pd.DataFrame(
        {
            "sample": ["sample_a", "sample_b"],
            "condition": ["before", "after"],
            "pair_id": ["subject_01", "subject_01"],
        }
    )
    second = pd.DataFrame(
        {
            "sample": ["sample_a", "sample_b"],
            "condition": ["site_1", "site_1"],
        }
    )

    normalized = normalize_uploaded_metadata(data, first)
    assert normalized["pair_id"].tolist() == ["subject_01", "subject_01"]
    combined = build_combined_metadata_frame(normalized, second)
    assert combined["pair_id"].tolist() == ["subject_01", "subject_01"]


def test_uploaded_pair_metadata_rejects_duplicate_samples() -> None:
    from app.services.annotation_processor import normalize_uploaded_metadata
    from app.services.metadata_upload_store import build_combined_metadata_frame

    data = pd.DataFrame(columns=["sample_a"])
    metadata = pd.DataFrame(
        {
            "sample": ["sample_a", "sample_a"],
            "condition": ["before", "after"],
            "pair_id": ["subject_01", "subject_01"],
        }
    )
    with pytest.raises(ValueError, match="each sample exactly once"):
        normalize_uploaded_metadata(data, metadata)
    with pytest.raises(ValueError, match="each sample exactly once"):
        build_combined_metadata_frame(metadata, metadata)


def test_ui_pairing_updates_canonical_annotation_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from app.schemas.annotation import SamplePairAssignment
    from app.services import annotation_store

    metadata = pd.DataFrame(
        {
            "sample": ["before_a", "before_b", "after_b", "after_a"],
            "condition": ["before", "before", "after", "after"],
        }
    )
    stored = SimpleNamespace(
        kind="protein",
        source_data=pd.DataFrame(),
        metadata=metadata,
        log2_data=pd.DataFrame(),
        filtered_data=pd.DataFrame(),
        is_log2_transformed=True,
        metadata_source="manual",
        filter_config=SimpleNamespace(),
        auto_detected=False,
        warnings=[],
        log2_auto_detected=False,
        imputation=None,
    )
    saved: dict[str, object] = {}
    monkeypatch.setattr(annotation_store, "get_annotation", lambda _kind: stored)
    monkeypatch.setattr(
        annotation_store,
        "update_uploaded_metadata_pair_ids",
        lambda _kind, _pair_ids: False,
    )

    def capture_save(**kwargs):
        saved.update(kwargs)
        return SimpleNamespace(**kwargs)

    monkeypatch.setattr(annotation_store, "save_annotation", capture_save)
    result = annotation_store.update_annotation_pairing(
        "protein",
        "before",
        "after",
        [
            SamplePairAssignment(
                condition1Sample="before_a",
                condition2Sample="after_a",
            ),
            SamplePairAssignment(
                condition1Sample="before_b",
                condition2Sample="after_b",
            ),
        ],
    )

    paired = result.metadata.set_index("sample")["pair_id"].to_dict()
    assert paired["before_a"] == paired["after_a"]
    assert paired["before_b"] == paired["after_b"]
    assert paired["before_a"] != paired["before_b"]


def test_ui_pairing_preserves_exact_sample_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from app.schemas.annotation import SamplePairAssignment
    from app.services import annotation_store

    stored = SimpleNamespace(
        kind="protein",
        source_data=pd.DataFrame(),
        metadata=pd.DataFrame(
            {
                "sample": [" before_a", "before_b", " after_a", "after_b"],
                "condition": ["before", "before", "after", "after"],
            }
        ),
        log2_data=pd.DataFrame(),
        filtered_data=pd.DataFrame(),
        is_log2_transformed=True,
        metadata_source="manual",
        filter_config=SimpleNamespace(),
        auto_detected=False,
        warnings=[],
        log2_auto_detected=False,
        imputation=None,
    )
    monkeypatch.setattr(annotation_store, "get_annotation", lambda _kind: stored)
    monkeypatch.setattr(
        annotation_store,
        "update_uploaded_metadata_pair_ids",
        lambda _kind, _pair_ids: False,
    )
    monkeypatch.setattr(
        annotation_store,
        "save_annotation",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )

    result = annotation_store.update_annotation_pairing(
        "protein",
        "before",
        "after",
        [
            SamplePairAssignment(
                condition1Sample=" before_a",
                condition2Sample=" after_a",
            ),
            SamplePairAssignment(
                condition1Sample="before_b",
                condition2Sample="after_b",
            ),
        ],
    )
    assert result.metadata.set_index("sample").loc[" before_a", "pair_id"]


def test_ui_pairing_excludes_unselected_samples_and_persists_blanks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from app.schemas.annotation import SamplePairAssignment
    from app.services import annotation_store

    metadata = pd.DataFrame(
        {
            "sample": ["before_a", "before_b", "before_c", "after_a", "after_b"],
            "condition": ["before", "before", "before", "after", "after"],
            "pair_id": ["old-a", "old-b", "old-c", "old-a", "old-b"],
        }
    )
    stored = SimpleNamespace(
        kind="protein",
        source_data=pd.DataFrame(),
        metadata=metadata,
        log2_data=pd.DataFrame(),
        filtered_data=pd.DataFrame(),
        is_log2_transformed=True,
        metadata_source="uploaded",
        filter_config=SimpleNamespace(),
        auto_detected=False,
        warnings=[],
        log2_auto_detected=False,
        imputation=None,
    )
    persisted: dict[str, str] = {}
    monkeypatch.setattr(annotation_store, "get_annotation", lambda _kind: stored)
    monkeypatch.setattr(
        annotation_store,
        "update_uploaded_metadata_pair_ids",
        lambda _kind, pair_ids: persisted.update(pair_ids) is None,
    )
    monkeypatch.setattr(
        annotation_store,
        "save_annotation",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )

    result = annotation_store.update_annotation_pairing(
        "protein",
        "before",
        "after",
        [
            SamplePairAssignment(
                condition1Sample="before_a",
                condition2Sample="after_a",
            ),
            SamplePairAssignment(
                condition1Sample="before_b",
                condition2Sample="after_b",
            ),
        ],
    )
    pair_ids = result.metadata.set_index("sample")["pair_id"].to_dict()
    assert pair_ids["before_a"] == pair_ids["after_a"]
    assert pair_ids["before_b"] == pair_ids["after_b"]
    assert pair_ids["before_c"] == ""
    assert persisted["before_c"] == ""


def test_manual_regeneration_preserves_saved_pair_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from app.services import annotation_store

    previous = pd.DataFrame(
        {
            "sample": ["before_a", "before_b", "after_a", "after_b"],
            "condition": ["before", "before", "after", "after"],
            "pair_id": ["ui-pair-1", "ui-pair-2", "ui-pair-1", "ui-pair-2"],
        }
    )
    regenerated = previous.drop(columns="pair_id")
    monkeypatch.setattr(
        annotation_store,
        "get_annotation",
        lambda _kind: SimpleNamespace(metadata=previous),
    )

    preserved = annotation_store.preserve_annotation_pair_ids("protein", regenerated)
    assert preserved["pair_id"].tolist() == previous["pair_id"].tolist()


def test_uploaded_metadata_pair_ids_survive_regeneration() -> None:
    from app.services.annotation_processor import normalize_uploaded_metadata
    from app.services.metadata_upload_store import (
        get_uploaded_metadata,
        save_uploaded_metadata,
        update_uploaded_metadata_pair_ids,
    )

    frame = pd.DataFrame(
        {
            "sample": ["before_a", "before_b", "after_a", "after_b"],
            "condition": ["before", "before", "after", "after"],
        }
    )
    save_uploaded_metadata(
        "protein",
        "metadata.csv",
        frame,
        package_name="pairing-regeneration-test",
        profile_name="Paired",
    )
    changed = update_uploaded_metadata_pair_ids(
        "protein",
        {
            "before_a": "ui-pair-1",
            "before_b": "ui-pair-2",
            "after_a": "ui-pair-1",
            "after_b": "ui-pair-2",
        },
        package_name="pairing-regeneration-test",
        profile_name="Paired",
    )
    stored = get_uploaded_metadata(
        "protein",
        package_name="pairing-regeneration-test",
        profile_name="Paired",
    )
    assert changed
    assert stored is not None
    regenerated = normalize_uploaded_metadata(
        pd.DataFrame(columns=frame["sample"].tolist()),
        stored.frame,
    )
    assert regenerated["pair_id"].tolist() == [
        "ui-pair-1",
        "ui-pair-2",
        "ui-pair-1",
        "ui-pair-2",
    ]


def test_uploaded_metadata_clears_previously_paired_unselected_samples() -> None:
    from app.services.metadata_upload_store import (
        get_uploaded_metadata,
        save_uploaded_metadata,
        update_uploaded_metadata_pair_ids,
    )

    frame = pd.DataFrame(
        {
            "sample": ["before_a", "before_b", "before_c", "after_a", "after_b"],
            "condition": ["before", "before", "before", "after", "after"],
            "pair_id": ["old-a", "old-b", "old-c", "old-a", "old-b"],
        }
    )
    save_uploaded_metadata(
        "protein",
        "metadata.csv",
        frame,
        package_name="partial-pairing-persistence-test",
        profile_name="Paired",
    )
    update_uploaded_metadata_pair_ids(
        "protein",
        {
            "before_a": "new-a",
            "before_b": "new-b",
            "before_c": "",
            "after_a": "new-a",
            "after_b": "new-b",
        },
        package_name="partial-pairing-persistence-test",
        profile_name="Paired",
    )
    stored = get_uploaded_metadata(
        "protein",
        package_name="partial-pairing-persistence-test",
        profile_name="Paired",
    )
    assert stored is not None
    pair_ids = stored.frame.set_index("sample")["pair_id"].to_dict()
    assert pair_ids["before_c"] == ""
    assert pair_ids["before_a"] == pair_ids["after_a"] == "new-a"


def test_ui_pairing_requires_every_sample_once(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from app.schemas.annotation import SamplePairAssignment
    from app.services import annotation_store

    stored = SimpleNamespace(
        metadata=pd.DataFrame(
            {
                "sample": ["before_a", "before_b", "after_a", "after_b"],
                "condition": ["before", "before", "after", "after"],
            }
        )
    )
    monkeypatch.setattr(annotation_store, "get_annotation", lambda _kind: stored)
    with pytest.raises(ValueError, match="only once"):
        annotation_store.update_annotation_pairing(
            "protein",
            "before",
            "after",
            [
                SamplePairAssignment(
                    condition1Sample="before_a",
                    condition2Sample="after_a",
                ),
                SamplePairAssignment(
                    condition1Sample="before_a",
                    condition2Sample="after_b",
                ),
            ],
        )


@pytest.fixture(params=["empty", "unrelated_annotation"])
def regulation_store_state(request):
    """Numerical unit fixtures must not depend on a viewer being loaded first."""
    from app.schemas.annotation import AnnotationFilterConfig
    from app.services import annotation_store

    snapshot = annotation_store.snapshot_annotation_session_state()
    try:
        annotation_store.reset_all_annotations()
        if request.param == "unrelated_annotation":
            frame = pd.DataFrame({"PTM_Collapse_key": ["unrelated"], "viewer_sample": [99.]})
            annotation_store.save_annotation(
                kind="phospho", source_data=frame, log2_data=frame, filtered_data=frame,
                metadata=pd.DataFrame({"sample": ["viewer_sample"], "condition": ["viewer_condition"]}),
                is_log2_transformed=True, metadata_source="manual",
                filter_config=AnnotationFilterConfig(), auto_detected=False, warnings=[],
            )
        yield
    finally:
        annotation_store.restore_annotation_session_state(snapshot)


def test_paired_phospho_paths_use_the_same_identity(
    monkeypatch: pytest.MonkeyPatch,
    regulation_store_state,
) -> None:
    from app.services import phospho_tools

    metadata = paired_metadata()
    protein_frame = paired_frame()

    phospho_frame = protein_frame.rename(columns={"ProteinNames": "UPD_seq"}).copy()
    phospho_frame["UPD_seq"] = [
        "AAAAAA*SAAAAAA",
        "BBBBBB*TBBBBBB",
        "CCCCCC*YCCCCCC",
        "DDDDDD*SDDDDDD",
    ]
    monkeypatch.setattr(
        phospho_tools,
        "_ksea_context",
        lambda **_kwargs: (phospho_frame.copy(), metadata.copy(), metadata["sample"].tolist()),
    )
    ksea = phospho_tools.ksea_table(
        condition1="before",
        condition2="after",
        data_source="data",
        test_type="paired",
        use_uncorrected=True,
    )
    assert ksea["n_pairs"].tolist() == [3, 4, 4, 4]
    assert ksea["log2FC"].tolist() == [-5.0, 0.0, -2.0, -1.0]
    with pytest.raises(ValueError, match="paired.*unpaired"):
        phospho_tools.ksea_table(
            condition1="before",
            condition2="after",
            data_source="data",
            test_type="paried",
        )

    regulation_frame = phospho_frame.rename(columns={"UPD_seq": "PTM_Collapse_key"}).copy()
    regulation_frame["Protein_group"] = ["P1", "P2", "P3", "P4"]
    monkeypatch.setattr(
        phospho_tools,
        "_phospho_regulation_context",
        lambda data_source="data": (
            regulation_frame.copy(),
            metadata.copy(),
            metadata["sample"].tolist(),
        ),
    )
    regulation = phospho_tools.phosprot_regulation_table(
        condition1="before",
        condition2="after",
        test_type="paired",
        use_uncorrected=True,
    )
    assert regulation["Protein_group"].tolist() == ["P3"]
    # log2FC is condition1 - condition2, so P3's +2 in "after" is reported as a
    # downregulated site of magnitude 2 here.
    assert regulation["Downregulated_count"].tolist() == [1]
    assert regulation["Downregulated_log2FC_sum"].tolist() == [2.0]
    with pytest.raises(ValueError, match="paired.*unpaired"):
        phospho_tools.phosprot_regulation_table(
            condition1="before",
            condition2="after",
            test_type="paried",
        )


def test_phosprot_regulation_uses_only_significant_site_log2fc(
    monkeypatch: pytest.MonkeyPatch,
    regulation_store_state,
) -> None:
    from app.services import phospho_tools
    from proteomicscopylot.notebook_functions import phosprot_regulation

    metadata = pd.DataFrame(
        {
            "sample": ["a1", "a2", "a3", "b1", "b2", "b3"],
            "condition": ["A", "A", "A", "B", "B", "B"],
        }
    )
    frame = pd.DataFrame(
        {
            "PTM_Collapse_key": ["up-1", "up-2", "down-1", "noise", "small"],
            "Protein_group": ["P1", "P1", "P1", "P1", "P2"],
            "a1": [10.0, 8.0, 15.0, 10.0, 10.0],
            "a2": [10.1, 8.2, 15.2, 11.0, 10.1],
            "a3": [9.9, 7.8, 14.8, 9.0, 9.9],
            "b1": [12.0, 9.5, 12.0, 10.5, 10.5],
            "b2": [12.1, 9.7, 12.2, 11.5, 10.6],
            "b3": [11.9, 9.3, 11.8, 9.5, 10.4],
        }
    )
    monkeypatch.setattr(
        phospho_tools,
        "_phospho_regulation_context",
        lambda data_source="data": (frame.copy(), metadata.copy(), metadata["sample"].tolist()),
    )

    result = phospho_tools.phosprot_regulation_table(
        condition1="A",
        condition2="B",
        p_value_threshold=0.05,
        log2fc_threshold=1.0,
        use_uncorrected=True,
    )
    assert result["Protein_group"].tolist() == ["P1"]
    # log2FC is condition1 - condition2, so the sites that rose in B relative
    # to A are reported as downregulated here; magnitudes are unchanged.
    assert result["Upregulated_count"].tolist() == [1]
    assert result["Downregulated_count"].tolist() == [2]
    assert result["Upregulated_log2FC_sum"].tolist() == pytest.approx([3.0])
    assert result["Downregulated_log2FC_sum"].tolist() == pytest.approx([3.5])
    assert "noise" not in result.loc[0, "Downregulated_sites"]
    assert phospho_tools.phosprot_regulation_png(
        condition1="A",
        condition2="B",
        p_value_threshold=0.05,
        log2fc_threshold=1.0,
        use_uncorrected=True,
    ).startswith(b"\x89PNG")
    assert "Cumulative Significant Up-Site log2FC" in phospho_tools.phosprot_regulation_html(
        condition1="A",
        condition2="B",
        p_value_threshold=0.05,
        log2fc_threshold=1.0,
        use_uncorrected=True,
    )

    stricter = phospho_tools.phosprot_regulation_table(
        condition1="A",
        condition2="B",
        p_value_threshold=0.05,
        log2fc_threshold=1.75,
        use_uncorrected=True,
    )
    assert stricter["Upregulated_count"].tolist() == [1]
    assert stricter["Upregulated_log2FC_sum"].tolist() == pytest.approx([3.0])
    assert stricter["Downregulated_log2FC_sum"].tolist() == pytest.approx([2.0])

    no_hits = phospho_tools.phosprot_regulation_table(
        condition1="A",
        condition2="B",
        p_value_threshold=1e-12,
        log2fc_threshold=1.0,
        use_uncorrected=True,
    )
    assert no_hits.empty
    assert {"x", "y", "color_val"} <= set(no_hits.columns)
    assert phospho_tools.phosprot_regulation_png(
        condition1="A",
        condition2="B",
        p_value_threshold=1e-12,
        log2fc_threshold=1.0,
        use_uncorrected=True,
    ).startswith(b"\x89PNG")

    figure = phosprot_regulation(
        frame,
        metadata,
        "A",
        "B",
        in_pval=0.05,
        in_log2fc=1.0,
        uncorrected=True,
    )
    assert list(figure.data[0].x) == pytest.approx([3.0])
    assert list(figure.data[0].y) == pytest.approx([3.5])
