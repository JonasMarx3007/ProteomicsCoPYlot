from __future__ import annotations

import numpy as np
import pandas as pd

from app.services import plot_images


def test_qc_correlation_plot_uses_log2_qc_frame(monkeypatch) -> None:
    log2_frame = pd.DataFrame(
        {
            "sample_a": [1.0, 2.0, 3.0, 8.0, np.nan],
            "sample_b": [1.0, 4.0, 5.0, 6.0, 9.0],
        }
    )
    metadata = pd.DataFrame(
        {
            "sample": ["sample_a", "sample_b"],
            "condition": ["A", "B"],
        }
    )

    monkeypatch.setattr(
        plot_images,
        "log2_qc_frame",
        lambda kind: log2_frame.copy(),
    )

    def fail_if_linear_source_is_used(kind):
        raise AssertionError("The correlation plot must not use reconstructed linear data.")

    monkeypatch.setattr(
        plot_images,
        "linear_qc_frame",
        fail_if_linear_source_is_used,
    )
    monkeypatch.setattr(
        plot_images,
        "_get_sample_columns",
        lambda kind, frame: ["sample_a", "sample_b"],
    )
    monkeypatch.setattr(
        plot_images,
        "_metadata_for_kind",
        lambda kind, frame, sample_columns: metadata.copy(),
    )

    png = plot_images.qc_correlation_plot(
        "protein",
        method="Matrix",
        width_cm=5,
        height_cm=5,
        dpi=40,
    )

    expected = log2_frame[["sample_a", "sample_b"]].corr().iloc[0, 1]
    assert np.isclose(
        expected,
        np.corrcoef(
            log2_frame[["sample_a", "sample_b"]].dropna().to_numpy().T
        )[0, 1],
    )
    assert png.startswith(b"\x89PNG\r\n\x1a\n")


def test_chat_correlation_context_uses_the_same_log2_frame_as_the_plot(monkeypatch) -> None:
    from app.services import ai_functions

    log2_frame = pd.DataFrame(
        {
            "sample_a": [20.0, 21.0, 22.0, 23.0, 24.0],
            "sample_b": [20.5, 21.4, 21.8, 23.3, 24.1],
        }
    )
    metadata = pd.DataFrame(
        {"sample": ["sample_a", "sample_b"], "condition": ["A", "A"]}
    )

    monkeypatch.setattr(plot_images, "log2_qc_frame", lambda kind: log2_frame.copy())
    monkeypatch.setattr(
        plot_images, "_get_sample_columns", lambda kind, frame: ["sample_a", "sample_b"]
    )
    monkeypatch.setattr(
        plot_images, "_metadata_for_kind", lambda kind, frame, columns: metadata.copy()
    )

    def fail_if_linear_source_is_used(kind):
        raise AssertionError(
            "The chat correlation context must not use reconstructed linear data."
        )

    monkeypatch.setattr(plot_images, "linear_qc_frame", fail_if_linear_source_is_used)

    lines = ai_functions._correlation_data_lines("protein")

    expected = log2_frame.corr(method="pearson").loc["sample_a", "sample_b"]
    summary = [line for line in lines if line.startswith("correlation_group_summary")]
    assert summary, lines
    assert f"mean_r={expected:.4f}" in summary[0], (summary[0], expected)
