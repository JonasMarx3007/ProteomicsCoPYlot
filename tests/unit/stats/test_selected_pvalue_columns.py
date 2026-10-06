"""Every p-value column means one thing, and the assistant reads the plotted one.

`adj_pval` used to hold the raw p-value whenever "use uncorrected p-values" was
on, and the plotted -log10 value lived in `neg_log10_adj_pval` either way. The
assistant looked for a `neg_log10_pval` column that never existed, defaulted it
to 0, and told the model "-log10 p = 0" next to p = 5e-12. Now `pval` is raw,
`adj_pval` is always Benjamini-Hochberg, `selected_pval` is the one significance
is called on, and `neg_log10_selected_pval` is what the volcano plots -- in the
backend, the pip package and R alike.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy.stats import false_discovery_control

from app.schemas.stats import AnovaRequest, VolcanoRequest
from app.services import ai_functions, stats_tools
from app.services.viewer_bootstrap import load_viewer_state
from proteomicscopylot import notebook_functions as notebook

ROOT = Path(__file__).resolve().parents[3]


def _volcano(raw: bool) -> pd.DataFrame:
    return pd.DataFrame(stats_tools.run_volcano(VolcanoRequest(
        kind="protein", dataSource="filtered", condition1="GRK", condition2="WT", identifier="workflow",
        pValueThreshold=0.05, log2fcThreshold=1.0, testType="unpaired", useUncorrected=raw,
    )).rows)


@pytest.mark.parametrize("raw", [False, True])
def test_volcano_columns_mean_one_thing(example_project, raw):
    frame = _volcano(raw)
    assert "neg_log10_adj_pval" not in frame.columns
    np.testing.assert_allclose(frame["adj_pval"], false_discovery_control(frame["pval"]), rtol=1e-12)
    np.testing.assert_array_equal(frame["selected_pval"], frame["pval"] if raw else frame["adj_pval"])
    np.testing.assert_allclose(frame["neg_log10_selected_pval"], -np.log10(frame["selected_pval"]), rtol=1e-12)
    called = frame["significance"].isin(["Upregulated", "Downregulated"])
    assert (frame.loc[called, "selected_pval"] < 0.05).all()


@pytest.mark.parametrize("raw", [False, True])
def test_anova_columns_and_significance_use_the_selected_p(example_project, raw):
    _, _, frame, _ = stats_tools._anova_dataframe(AnovaRequest(
        kind="protein", dataSource="filtered", identifier="workflow", pValueThreshold=0.05, useUncorrected=raw,
    ))
    np.testing.assert_allclose(frame["adj_pval"], false_discovery_control(frame["pval"]), rtol=1e-12)
    np.testing.assert_array_equal(frame["selected_pval"], frame["pval"] if raw else frame["adj_pval"])
    assert ((frame["significance"] == "Significant") == (frame["selected_pval"] < 0.05)).all()


def test_raw_p_evidence_reports_the_plotted_value(example_project):
    """The regression: minus_log10_selected_p was 0 for every ranked row."""
    text = ai_functions.stats_volcano_plot(mode={
        "source": "volcano", "dataSource": "filtered", "condition1": "GRK", "condition2": "WT",
        "pValueThreshold": 0.05, "log2fcThreshold": 1.0, "testType": "unpaired", "useUncorrected": True,
    })["summary"]
    rows = re.findall(r"selected_p_value=([^|]+)\|minus_log10_selected_p=([^|]+)\|", text)
    assert rows, "no ranked volcano rows in the evidence"
    for p_value, minus_log10 in rows:
        assert float(minus_log10) > 0
        assert float(minus_log10) == pytest.approx(-np.log10(float(p_value)), abs=0.01)  # printed to 2 decimals


@pytest.mark.parametrize("raw", [False, True])
def test_the_package_uses_the_same_columns(raw):
    rng = np.random.default_rng(3)
    samples = [f"{group}{i}" for group in "AB" for i in range(4)]
    data = pd.DataFrame(rng.normal(size=(50, 8)), columns=samples)
    data.iloc[:10, 4:] += 3
    data.insert(0, "ProteinNames", [f"P{i}" for i in range(50)])
    meta = pd.DataFrame({"sample": samples, "condition": [s[0] for s in samples]})
    volcano = notebook.volcano_data_f(data, meta, "A", "B", uncorrected=raw)
    np.testing.assert_allclose(volcano["adj_pval"], false_discovery_control(volcano["pval"]), rtol=1e-12)
    np.testing.assert_array_equal(volcano["selected_pval"], volcano["pval"] if raw else volcano["adj_pval"])
    assert "neg_log10_selected_pval" in volcano.columns and "neg_log10_adj_pval" not in volcano.columns
    anova = notebook.anova_data_f(data, meta, uncorrected=raw)
    np.testing.assert_array_equal(anova["selected_pval"], anova["pval"] if raw else anova["adj_pval"])
