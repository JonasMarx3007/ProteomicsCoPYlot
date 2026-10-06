"""Features with no value in any sample are left out of completeness, in all three.

A feature missing in every selected sample says nothing about how complete those
samples are -- it was identified elsewhere, or never quantified. The web app
leaves such rows out of the completeness plot, heatmap, tables and overall
percentage and states how many there were; the packages used to count them as
missing everywhere, so the same data gave different percentages (21 rows of the
phosphosite example). The packages now leave them out too.
"""
from __future__ import annotations

import json
import subprocess

import numpy as np
import pandas as pd
import pytest

from proteomicscopylot import notebook_functions as nb

SAMPLES = ["A_1", "A_2", "B_1", "B_2"]
# Two quantified features, one with a gap, and one never quantified.
DATA = pd.DataFrame({
    "ProteinNames": ["P1", "P2", "never"],
    "A_1": [20.0, 21.0, np.nan],
    "A_2": [20.5, np.nan, np.nan],
    "B_1": [19.0, 22.0, np.nan],
    "B_2": [19.5, 21.5, np.nan],
})
META = pd.DataFrame({"sample": SAMPLES, "condition": ["A", "A", "B", "B"]})
# One missing value among the 8 of the two quantified rows.
EXPECTED_PERCENT = 12.5


def test_the_python_package_leaves_the_unquantified_row_out() -> None:
    assert nb.all_miss_val(DATA, META) == EXPECTED_PERCENT
    samples = nb.missing_sample_table(DATA, META, id=False)
    assert samples["Counts"].tolist() == [0, 1, 0, 0]
    assert samples["%_missing_values"].tolist() == [0.0, 50.0, 0.0, 0.0]
    features = nb.missing_protein_table(DATA, META, id=False)
    assert dict(zip(features["n_MissingProteinValues"], features["Counts"])) == {0: 1, 1: 1}
    fig = nb.missing_value_heatmap(DATA, META, id=False)
    try:
        assert fig.axes[0].collections[0].get_array().size == 2 * len(SAMPLES)
    finally:
        import matplotlib.pyplot as plt

        plt.close(fig)


@pytest.mark.requires_r("jsonlite")
def test_the_r_package_leaves_it_out_too(rscript, tmp_path) -> None:
    DATA.to_csv(tmp_path / "data.csv", index=False)
    META.to_csv(tmp_path / "meta.csv", index=False)
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    script = f"""
      source({str(root / 'proteomicscopylot' / 'notebook_functions.R')!r})
      data <- read.csv({str(tmp_path / 'data.csv')!r}, check.names = FALSE)
      meta <- read.csv({str(tmp_path / 'meta.csv')!r}, check.names = FALSE)
      samples <- missing_sample_table(data, meta, id = FALSE)
      features <- missing_protein_table(data, meta, id = FALSE)
      cat(jsonlite::toJSON(list(
        percent = all_miss_val(data, meta),
        sample_counts = samples$Counts,
        sample_percent = samples$`%_missing_values`,
        feature_missing = features$n_MissingProteinValues,
        feature_counts = features$Counts
      ), auto_unbox = TRUE))
    """
    result = subprocess.run([rscript, "-e", script], capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stderr[-2000:]
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert out["percent"] == EXPECTED_PERCENT
    assert out["sample_counts"] == [0, 1, 0, 0]
    assert out["sample_percent"] == [0, 50, 0, 0]
    assert dict(zip(out["feature_missing"], out["feature_counts"])) == {0: 1, 1: 1}
