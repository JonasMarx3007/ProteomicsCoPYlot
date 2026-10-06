"""Results say how many imputed values sit behind every row.

Imputed values enter the t-test and ANOVA as if measured: they count towards n
and the degrees of freedom. On the bundled phosphosite data (GRK vs WT) imputing
raised the down-regulated calls from 239 to about 700, and most of the new calls
had three or more of five GRK values imputed -- GRK is missing 20-31% of values,
WT about 5%. The tests are unchanged; what changed is that every volcano, ANOVA
and Kinase Library table built on imputed data now carries `n_imputed__<condition>`
and `imputed_values`, identically in the backend, the pip package and R, and the
report says that imputed values were tested as observations.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.schemas.data_tools import ImputationRunRequest
from app.schemas.stats import AnovaRequest, VolcanoControlRequest, VolcanoRequest
from app.services import functions, stats_tools
from app.services.annotation_store import get_annotation
from app.services.data_tools import run_imputation
from app.services.viewer_bootstrap import load_viewer_state
from proteomicscopylot import notebook_functions as notebook

ROOT = Path(__file__).resolve().parents[3]


def _frames():
    samples = ["a1", "a2", "a3", "b1", "b2", "b3"]
    observed = pd.DataFrame(
        [[1.0, np.nan, 1.2, 2.0, 2.1, np.nan],
         [np.nan, np.nan, 1.0, 1.0, 1.1, 0.9],
         [1.0, 1.1, 0.9, 1.0, 1.1, 0.9]],
        columns=samples, index=[10, 11, 12],
    )
    imputed = observed.fillna(-3.0)
    return samples, observed, imputed


def test_counts_are_per_group_and_total_and_match_the_package():
    samples, observed, imputed = _frames()
    groups = {"A": samples[:3], "B": samples[3:]}
    backend = functions.imputed_value_counts(functions.imputed_cell_mask(imputed, observed), groups)
    package = notebook.imputed_value_counts(notebook.imputed_cell_mask(imputed, observed), groups)
    pd.testing.assert_frame_equal(backend, package)
    assert backend['n_measured__A'].tolist() == [2, 1, 3]
    assert backend['n_fully_imputed__A'].tolist() == [1, 2, 0]
    assert backend['n_partially_imputed__A'].tolist() == [0, 0, 0]
    assert backend["n_imputed__A"].tolist() == [1, 2, 0]
    assert backend["n_imputed__B"].tolist() == [1, 0, 0]
    assert backend["imputed_values"].tolist() == [2, 2, 0]


def test_phosphoprotein_values_without_a_measured_site_count_as_imputed():
    frame = pd.DataFrame({
        "s1": [1.0, 2.0, np.nan], "s2": [1.0, 2.0, 3.0],
        "site_observed__s1": [0, 2, 0], "site_observed__s2": [1, 0, 1],
        "site_supplied__s1": [2, 2, 0], "site_supplied__s2": [2, 2, 1],
    })
    for module in (functions, notebook):
        mask = module.site_observed_imputed_mask(frame, ["s1", "s2"])
        assert mask.to_numpy().tolist() == [[1, 2], [0, 1], [-1, 0]]
        counts = module.imputed_value_counts(mask, {'A': ['s1', 's2']})
        assert counts['n_partially_imputed__A'].tolist() == [1, 0, 0]
        assert counts['n_fully_imputed__A'].tolist() == [1, 1, 0]
        assert counts['n_measured__A'].tolist() == [0, 1, 1]
        assert counts['imputed_values'].tolist() == [2, 1, 0]
    assert functions.site_observed_imputed_mask(frame.drop(columns="site_observed__s2"), ["s1", "s2"]) is None


def test_package_volcano_and_anova_carry_counts_only_when_told_what_was_observed():
    samples, observed, imputed = _frames()
    meta = pd.DataFrame({"sample": samples, "condition": ["A"] * 3 + ["B"] * 3})
    data = imputed.copy()
    data.insert(0, "ProteinNames", ["P1", "P2", "P3"])
    plain = notebook.volcano_data_f(data, meta, "A", "B", in_log2fc=0)
    assert "imputed_values" not in plain.columns
    counted = notebook.volcano_data_f(data, meta, "A", "B", in_log2fc=0, observed=observed)
    assert counted["imputed_values"].tolist() == [2, 2, 0]
    np.testing.assert_allclose(counted["pval"], plain["pval"])
    anova = notebook.anova_data_f(data, meta, observed=observed)
    assert dict(zip(anova["ProteinNames"], anova["imputed_values"])) == {"P1": 2, "P2": 2, "P3": 0}
    with pytest.raises(ValueError, match="pre-imputation matrix"):
        notebook.volcano_data_f(data, meta, "A", "B", observed=observed.iloc[:2])


@pytest.fixture(scope="module")
def imputed_phospho():
    load_viewer_state(ROOT / "tests" / "fixtures" / "viewer_config.json")
    annotation = get_annotation("phospho")
    before = (annotation.imputed_data, getattr(annotation, "imputation", None))
    run_imputation(ImputationRunRequest(kind="phospho", seed=1337))
    yield get_annotation("phospho")
    annotation = get_annotation("phospho")
    annotation.imputed_data, annotation.imputation = before


def _volcano(data_source, **extra):
    request = (VolcanoControlRequest if extra else VolcanoRequest)(
        kind="phospho", dataSource=data_source, condition1="GRK", condition2="WT",
        identifier="workflow", pValueThreshold=0.05, log2fcThreshold=1.0,
        testType="unpaired", useUncorrected=False, **extra,
    )
    return pd.DataFrame(stats_tools.run_volcano(request).rows)


def test_volcano_counts_every_imputed_cell_and_matches_the_package(imputed_phospho):
    filtered = _volcano("filtered")
    assert "imputed_values" not in filtered.columns, "no imputation, no count columns"

    frame = _volcano("imputed")
    assert {'n_imputed__GRK', 'n_imputed__WT', 'imputed_values', 'n_measured__GRK', 'n_partially_imputed__WT'} <= set(frame.columns)
    meta = imputed_phospho.metadata
    samples = meta["sample"].tolist()
    expected = (imputed_phospho.filtered_data[samples].isna() & imputed_phospho.imputed_data[samples].notna())
    per_key = dict(zip(imputed_phospho.imputed_data["PTM_Collapse_key"], expected.sum(axis=1)))
    assert all(per_key[key] == total for key, total in zip(frame["PTM_Collapse_key"], frame["imputed_values"]))

    package = notebook.volcano_data_f(
        imputed_phospho.imputed_data, meta, "GRK", "WT", workflow="Phosphosite",
        test_type="unpaired", observed=imputed_phospho.filtered_data,
    )
    for column in ("n_imputed__GRK", "n_imputed__WT", "imputed_values"):
        assert frame[column].tolist() == package[column].tolist()


def test_anova_carries_counts(imputed_phospho):
    _, _, frame, _ = stats_tools._anova_dataframe(AnovaRequest(
        kind="phospho", dataSource="imputed", identifier="workflow",
        pValueThreshold=0.05, useUncorrected=False,
    ))
    assert {"n_imputed__GRK", "n_imputed__WT", "imputed_values"} <= set(frame.columns)
    assert (frame["imputed_values"] == frame["n_imputed__GRK"] + frame["n_imputed__WT"]).all()


def test_report_states_imputed_values_were_tested_as_observations(imputed_phospho):
    from app.services import report_function

    html = report_function._data_provenance_html(
        kind="phospho", data_source="imputed", subject="this comparison", tested=True
    )
    assert "treated as observed values in the statistical test" in html
    assert report_function.IMPUTED_AS_OBSERVED_SENTENCE not in report_function._data_provenance_html(
        kind="phospho", data_source="imputed", subject="this plot"
    ), "a PCA is not a test"
