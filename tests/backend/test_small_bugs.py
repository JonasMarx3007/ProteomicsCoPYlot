from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services import upload_limits
from app.services.completeness_tools import (
    _missing_value_plot_from_matrix,
    _peptide_quantity_column,
)


def _missing_matrix() -> pd.DataFrame:
    rng = np.random.default_rng(4)
    values = pd.DataFrame(rng.normal(20, 2, (400, 8)), columns=[f"s{i}" for i in range(8)])
    holes = rng.integers(0, 9, 400)
    for row, count in enumerate(holes):
        if count:
            values.iloc[row, :count] = np.nan
    return values


def _plot_counts(matrix: pd.DataFrame, bin_count: int) -> int:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    png = _missing_value_plot_from_matrix(
        matrix,
        title_label="Protein",
        bin_count=bin_count,
        header=False,
        text=False,
        text_size=8,
        color="#2563eb",
        width_cm=10,
        height_cm=6,
        dpi=72,
    )
    plt.close("all")
    assert png[:4] == b"\x89PNG"
    na = matrix.isna().sum(axis=1)
    return int((na != matrix.shape[1]).sum())


def test_never_identified_features_are_excluded_regardless_of_binning() -> None:
    matrix = _missing_matrix()
    all_missing = int((matrix.isna().sum(axis=1) == matrix.shape[1]).sum())
    assert all_missing > 0, "fixture must contain never-identified features"
    assert _plot_counts(matrix, 0) == _plot_counts(matrix, 3) == len(matrix) - all_missing


def test_missing_value_plot_renders_under_both_binning_modes() -> None:
    matrix = _missing_matrix()
    for bin_count in (0, 3, 5):
        assert _plot_counts(matrix, bin_count) > 0


@pytest.mark.parametrize(
    "column",
    ["Precursor.Quantity", "PG.Quantity", "Intensity", "LFQ intensity", "Abundance", "iBAQ"],
)
def test_recognised_quantity_columns_are_found(column: str) -> None:
    frame = pd.DataFrame({"Charge": [2, 3], "RT": [10.1, 12.4], column: [1.0, 2.0]})
    assert _peptide_quantity_column(frame) == column


def test_precursor_quantity_wins_over_other_candidates() -> None:
    frame = pd.DataFrame({"Intensity": [1.0], "Precursor.Quantity": [2.0]})
    assert _peptide_quantity_column(frame) == "Precursor.Quantity"


def test_missing_quantity_column_raises_instead_of_using_retention_time() -> None:
    frame = pd.DataFrame({"Charge": [2, 3], "RT": [10.1, 12.4], "Q.Value": [0.001, 0.004]})
    with pytest.raises(ValueError) as excinfo:
        _peptide_quantity_column(frame)
    message = str(excinfo.value)
    assert "Precursor.Quantity" in message
    assert "Charge" in message, "the error should list what was actually found"


class _StreamOnlyUpload:

    def __init__(self, payload: bytes) -> None:
        self.file = io.BytesIO(payload)
        self.size = None
        self.filename = "payload.csv"


def test_oversized_upload_is_rejected_when_size_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(upload_limits, "upload_max_bytes", lambda: 100)

    class Sized:
        size = 101
        file = io.BytesIO(b"x" * 101)

    with pytest.raises(ValueError):
        upload_limits.ensure_upload_size(Sized(), label="Test upload")


def test_oversized_upload_is_rejected_when_size_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(upload_limits, "upload_max_bytes", lambda: 100)
    with pytest.raises(ValueError):
        upload_limits.ensure_upload_size(_StreamOnlyUpload(b"x" * 500), label="Test upload")


def test_acceptable_upload_passes_and_stream_is_rewound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(upload_limits, "upload_max_bytes", lambda: 1000)
    upload = _StreamOnlyUpload(b"abc123" * 10)
    upload_limits.ensure_upload_size(upload, label="Test upload")
    assert upload.file.read() == b"abc123" * 10


def test_unseekable_stream_does_not_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(upload_limits, "upload_max_bytes", lambda: 1000)

    class Unseekable:
        size = None

        def __init__(self) -> None:
            self._data = io.BytesIO(b"y" * 50)

        @property
        def file(self):
            outer = self

            class _Inner:
                def read(self, n: int = -1) -> bytes:
                    return outer._data.read(n)

                def tell(self):
                    raise OSError("not seekable")

            return _Inner()

    upload_limits.ensure_upload_size(Unseekable(), label="Test upload")


def test_configured_but_unmaterialized_imputation_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import functions

    class _Imputation:
        mode = "quantile"
        applied = False
        qValue = 0.01
        adjustStd = 0.3
        seed = 1337
        sampleWise = False
        downShift = 1.8
        width = 0.3

    class _Annotation:
        metadata = pd.DataFrame({"sample": ["a", "b"], "condition": ["x", "x"]})
        filtered_data = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0]})
        log2_data = filtered_data
        imputation = _Imputation()
        imputed_data = pd.DataFrame()

    monkeypatch.setattr(
        "app.services.annotation_store.get_annotation", lambda kind: _Annotation()
    )
    monkeypatch.setattr(
        "app.services.data_tools._get_current_frame", lambda kind: _Annotation.filtered_data
    )

    with pytest.raises(ValueError, match="Run imputation successfully first"):
        functions.select_matrix("protein", data_source="imputed")


def test_imputed_request_uses_exact_stored_matrix_without_recomputing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import functions

    stored_imputed = pd.DataFrame({"a": [-10.0, 2.0], "b": [3.0, -11.0]})

    class _Imputation:
        mode = "quantile"
        applied = True

    class _Annotation:
        metadata = pd.DataFrame({"sample": ["a", "b"], "condition": ["x", "x"]})
        filtered_data = pd.DataFrame({"a": [1.0, np.nan], "b": [3.0, np.nan]})
        log2_data = filtered_data
        imputation = _Imputation()
        imputed_data = stored_imputed

    monkeypatch.setattr(
        "app.services.annotation_store.get_annotation", lambda kind: _Annotation()
    )
    monkeypatch.setattr(
        "app.services.data_tools._get_current_frame", lambda kind: _Annotation.filtered_data
    )
    monkeypatch.setattr(
        functions,
        "impute_values_with_diagnostics",
        lambda **kwargs: pytest.fail("stored imputation must not be recomputed"),
    )

    source, frame, _ = functions.select_matrix("protein", "imputed")
    assert source == "imputed"
    pd.testing.assert_frame_equal(frame, stored_imputed)


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
