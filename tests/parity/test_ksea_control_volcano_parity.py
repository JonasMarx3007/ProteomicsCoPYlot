from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.schemas.stats import VolcanoControlRequest, VolcanoRequest
from app.services import phospho_tools, stats_tools


CONDITIONS = ("condition-1", "control-1", "condition-2", "control-2")


@pytest.mark.parametrize("sequence,expected", [
    ("AAAAAAAs*AAAAAAA", "AAAAAAASAAAAAAA"),
    ("s*AAAAAAA", "_______SAAAAAAA"),
    ("AAAAAAAt*", "AAAAAAAT_______"),
    ("ACDy*EFG", "____ACDYEFG____"),
])
def test_ksea_preserves_all_available_flanks(sequence, expected):
    from proteomicscopylot.notebook_functions import convert_to_centered
    assert phospho_tools._convert_to_centered(sequence) == expected
    assert convert_to_centered(sequence) == expected


@pytest.mark.parametrize("control", [False, True])
def test_volcano_figure_labels_actual_contrast(control):
    frame = pd.DataFrame(columns=["significance"])
    fig = stats_tools._volcano_figure(
        frame, label_column="Genes", condition1="A", condition2="B",
        condition1_control="C" if control else None,
        condition2_control="D" if control else None,
        p_value_threshold=0.05, log2fc_threshold=1,
        use_uncorrected=False, highlight_terms=[],
    )
    contrast = "(A - C) - (B - D)" if control else "A - B"
    assert fig.layout.xaxis.title.text == f"log2 fold change ({contrast})"
    assert ("controls: C vs D" in fig.layout.title.text) is control


def _control_fixture(
    feature_count: int,
    *,
    seed: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    samples = [
        f"{condition}-replicate-{replicate}"
        for condition in CONDITIONS
        for replicate in range(1, 5)
    ]
    metadata = pd.DataFrame(
        {
            "sample": samples,
            "condition": [
                condition
                for condition in CONDITIONS
                for _ in range(4)
            ],
            "pair_id": [
                str(replicate)
                for _ in CONDITIONS
                for replicate in range(1, 5)
            ],
        }
    )
    frame = pd.DataFrame(
        rng.normal(size=(feature_count, len(samples))),
        columns=samples,
    )
    frame.insert(0, "UPD_seq", ["AAAAAA*SAAAAAA"] * feature_count)
    frame.insert(
        0,
        "PTM_Collapse_key",
        [f"site-{index}" for index in range(feature_count)],
    )
    return frame, metadata


def _patch_stats_source(
    monkeypatch: pytest.MonkeyPatch,
    frame: pd.DataFrame,
    metadata: pd.DataFrame,
) -> None:
    monkeypatch.setattr(
        stats_tools,
        "_stats_source",
        lambda kind, data_source: ("filtered", frame.copy(), metadata.copy(), []),
    )
    monkeypatch.setattr(
        phospho_tools,
        "_ksea_context",
        lambda **_kwargs: (frame.copy(), metadata.copy(), metadata["sample"].tolist()),
    )


@pytest.mark.parametrize("use_uncorrected", [False, True])
@pytest.mark.parametrize(
    "test_type",
    ["unpaired", "unpaired_welch", "paired"],
)
@pytest.mark.parametrize("data_source", ["data", "filtered", "imputed"])
def test_ksea_standard_formats_exact_volcano_output(
    monkeypatch: pytest.MonkeyPatch,
    use_uncorrected: bool,
    test_type: str,
    data_source: str,
) -> None:
    frame, metadata = _control_fixture(40, seed=17)
    _patch_stats_source(monkeypatch, frame, metadata)

    direct = stats_tools.run_volcano(
        VolcanoRequest(
            kind="phospho",
            dataSource=data_source,
            condition1=CONDITIONS[0],
            condition2=CONDITIONS[2],
            identifier="workflow",
            pValueThreshold=0.05,
            log2fcThreshold=0.0,
            testType=test_type,
            useUncorrected=use_uncorrected,
        )
    )
    ksea = phospho_tools.ksea_table(
        source="volcano",
        data_source=data_source,
        condition1=CONDITIONS[0],
        condition2=CONDITIONS[2],
        p_value_threshold=0.05,
        log2fc_threshold=0.0,
        test_type=test_type,
        use_uncorrected=use_uncorrected,
    )

    direct_frame = pd.DataFrame(direct.rows)
    for column in ("log2FC", "pval", "adj_pval", "neg_log10_selected_pval"):
        assert np.allclose(ksea[column], direct_frame[column])
    assert ksea["significance"].tolist() == direct_frame["significance"].tolist()
    assert ksea["UPD_seq"].tolist() == [
        phospho_tools._convert_to_centered(value)
        for value in direct_frame["UPD_seq"].tolist()
    ]


@pytest.mark.parametrize("use_uncorrected", [False, True])
@pytest.mark.parametrize(
    "test_type",
    ["unpaired", "unpaired_welch", "paired"],
)
@pytest.mark.parametrize("data_source", ["data", "filtered", "imputed"])
def test_ksea_control_formats_exact_control_volcano_output(
    monkeypatch: pytest.MonkeyPatch,
    use_uncorrected: bool,
    test_type: str,
    data_source: str,
) -> None:
    frame, metadata = _control_fixture(40, seed=7)
    _patch_stats_source(monkeypatch, frame, metadata)

    direct = stats_tools.run_volcano_control(
        VolcanoControlRequest(
            kind="phospho",
            dataSource=data_source,
            condition1=CONDITIONS[0],
            condition1Control=CONDITIONS[1],
            condition2=CONDITIONS[2],
            condition2Control=CONDITIONS[3],
            identifier="workflow",
            pValueThreshold=0.05,
            log2fcThreshold=0.0,
            testType=test_type,
            useUncorrected=use_uncorrected,
        )
    )
    ksea = phospho_tools.ksea_table(
        source="volcano_control",
        data_source=data_source,
        condition1=CONDITIONS[0],
        condition1_control=CONDITIONS[1],
        condition2=CONDITIONS[2],
        condition2_control=CONDITIONS[3],
        p_value_threshold=0.05,
        log2fc_threshold=0.0,
        test_type=test_type,
        use_uncorrected=use_uncorrected,
    )

    direct_frame = pd.DataFrame(direct.rows)
    for column in ("log2FC", "pval", "adj_pval", "neg_log10_selected_pval"):
        assert np.allclose(ksea[column], direct_frame[column])
    assert ksea["significance"].tolist() == direct_frame["significance"].tolist()
    assert ksea["UPD_seq"].tolist() == [
        phospho_tools._convert_to_centered(value)
        for value in direct_frame["UPD_seq"].tolist()
    ]


def test_ksea_control_null_calibration_includes_all_four_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame, metadata = _control_fixture(8_000, seed=20260803)
    _patch_stats_source(monkeypatch, frame, metadata)

    result = phospho_tools.ksea_table(
        source="volcano_control",
        data_source="data",
        condition1=CONDITIONS[0],
        condition1_control=CONDITIONS[1],
        condition2=CONDITIONS[2],
        condition2_control=CONDITIONS[3],
        p_value_threshold=0.05,
        log2fc_threshold=0.0,
        test_type="unpaired",
        use_uncorrected=True,
    )

    false_positive_fraction = float((result["pval"] < 0.05).mean())
    assert 0.04 <= false_positive_fraction <= 0.06
