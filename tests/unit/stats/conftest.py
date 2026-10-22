"""Shared statistical plot fixtures."""
import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def volcano_frame() -> pd.DataFrame:
    """A volcano-shaped frame: two tails and a large non-significant cloud."""
    rng = np.random.default_rng(20260916)
    size = 300
    frame = pd.DataFrame(
        {
            "ProteinNames": [f"P{index:04d}" for index in range(size)],
            "log2FC": rng.normal(0, 0.4, size),
            "neg_log10_selected_pval": rng.uniform(0, 1.2, size),
        }
    )
    frame["significance"] = "Not significant"
    frame.loc[:19, ["log2FC", "neg_log10_selected_pval", "significance"]] = None
    frame.loc[:19, "log2FC"] = rng.uniform(1.2, 3.0, 20)
    frame.loc[:19, "neg_log10_selected_pval"] = rng.uniform(2.0, 6.0, 20)
    frame.loc[:19, "significance"] = "Upregulated"
    frame.loc[20:39, "log2FC"] = rng.uniform(-3.0, -1.2, 20)
    frame.loc[20:39, "neg_log10_selected_pval"] = rng.uniform(2.0, 6.0, 20)
    frame.loc[20:39, "significance"] = "Downregulated"
    return frame
