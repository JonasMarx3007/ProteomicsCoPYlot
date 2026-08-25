from __future__ import annotations

import matplotlib.pyplot as plt
import pandas as pd
import pytest

from proteomicscopylot.notebook_functions import cov_plot


@pytest.fixture
def cv_input() -> tuple[pd.DataFrame, pd.DataFrame]:
    data = pd.DataFrame(
        {
            "ProteinNames": ["P1", "P2"],
            "sample_1": [100.0, 200.0],
            "sample_2": [110.0, 220.0],
        }
    )
    metadata = pd.DataFrame(
        {
            "sample": ["sample_1", "sample_2"],
            "condition": ["control", "control"],
        }
    )
    return data, metadata


def test_cov_plot_requires_an_explicit_scale(cv_input) -> None:
    data, metadata = cv_input

    with pytest.raises(ValueError, match="requires data_scale='linear'"):
        cov_plot(data, metadata)


def test_cov_plot_rejects_log2_data(cv_input) -> None:
    data, metadata = cv_input

    with pytest.raises(ValueError, match="requires linear intensities"):
        cov_plot(data, metadata, data_scale="log2")


def test_cov_plot_accepts_explicit_linear_data(cv_input) -> None:
    data, metadata = cv_input

    figure = cov_plot(data, metadata, data_scale=" linear ")
    try:
        assert figure.axes[0].get_ylabel() == "Coefficient of Variation (%)"
    finally:
        plt.close(figure)
