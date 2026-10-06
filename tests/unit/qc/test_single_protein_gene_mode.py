"""Single-protein gene mode: one median per sample, with counts.

Split out of test_small_bugs.py (2026-10-02)."""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]

from app.services import upload_limits
from app.services.completeness_tools import (
    _missing_value_plot_from_matrix,
    _peptide_quantity_column,
)



def test_single_protein_gene_mode_uses_one_median_per_sample_and_reports_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import single_protein_tools

    samples = ["a1", "a2", "a3", "b1", "b2", "b3"]
    frame = pd.DataFrame(
        {
            "ProteinNames": ["P1", "P2", "P3", "P10"],
            "GeneNames": ["GENE1", "GENE1;ALT", "GENE1;GENE1", "GENE10"],
            "a1": [0.0, 0.0, 0.0, 999.0],
            "a2": [2.0, 4.0, 100.0, 999.0],
            "a3": [np.nan, 6.0, 8.0, 999.0],
            "b1": [10.0, 20.0, 30.0, 999.0],
            "b2": [12.0, np.nan, 16.0, 999.0],
            "b3": [14.0, 24.0, 34.0, 999.0],
        }
    )
    metadata = pd.DataFrame(
        {
            "sample": samples,
            "condition": ["A", "A", "A", "B", "B", "B"],
        }
    )

    def use_frame(current: pd.DataFrame) -> None:
        monkeypatch.setattr(
            single_protein_tools,
            "_analysis_frame",
            lambda kind, data_source="data": (current.copy(), samples, metadata.copy()),
        )

    use_frame(frame)
    box = single_protein_tools.single_protein_boxplot_table(
        "protein",
        "gene1",
        ["A", "B"],
        identifier="genes",
    )
    line = single_protein_tools.single_protein_lineplot_table(
        "protein",
        ["gene1"],
        ["A", "B"],
        identifier="genes",
    )

    assert box["Condition"].tolist() == ["A", "B"]
    assert box["N"].tolist() == [3, 3]
    assert box["SampleCount"].tolist() == [3, 3]
    assert box["SourceFeatureCount"].tolist() == [3, 3]
    assert box["Median"].tolist() == [4.0, 20.0]
    assert box["SourceFeatures"].tolist() == ["P1; P2; P3", "P1; P2; P3"]
    assert box["Aggregation"].tolist() == ["Per-sample median", "Per-sample median"]
    assert box["Warning"].str.contains("Combined 3 source features").all()

    assert line["Feature"].unique().tolist() == ["gene1"]
    assert line["Sample"].tolist() == ["A_1", "A_2", "A_3", "B_1", "B_2", "B_3"]
    assert line["Value"].tolist() == [0.0, 4.0, 7.0, 20.0, 14.0, 24.0]
    assert line["SampleCount"].unique().tolist() == [6]
    assert line["SourceFeatureCount"].unique().tolist() == [3]
    assert line["SourceFeatures"].unique().tolist() == ["P1; P2; P3"]
    assert line["Warning"].str.contains("Combined 3 source features").all()

    use_frame(frame.iloc[[3, 2, 0, 1]].reset_index(drop=True))
    reordered_box = single_protein_tools.single_protein_boxplot_table(
        "protein",
        "GENE1",
        ["A", "B"],
        identifier="genes",
    )
    reordered_line = single_protein_tools.single_protein_lineplot_table(
        "protein",
        ["GENE1"],
        ["A", "B"],
        identifier="genes",
    )

    pd.testing.assert_frame_equal(
        box.drop(columns="Warning"),
        reordered_box.drop(columns="Warning"),
    )
    assert reordered_line["Value"].tolist() == line["Value"].tolist()
    assert reordered_line["SourceFeatures"].tolist() == line["SourceFeatures"].tolist()
