from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]

from app.services import stats_tools as st
from app.services.functions import constant_within_group

REPLICATES = 3
SAMPLES = [f"{c}_{i}" for c in ("A", "B") for i in range(REPLICATES)]
METADATA = pd.DataFrame(
    {"sample": SAMPLES, "condition": [s.split("_")[0] for s in SAMPLES]}
)
FLOOR_ROWS = range(1900, 1912)


@pytest.mark.parametrize("method", ["unpaired", "unpaired_welch", "paired"])
def test_self_comparisons_are_rejected_before_calculation(method):
    from fastapi.testclient import TestClient
    from app.main import app
    from proteomicscopylot import notebook_functions as nb

    with TestClient(app) as client:
        response = client.post("/api/stats/volcano/run", json={
            "kind": "protein", "condition1": "A", "condition2": "A", "testType": method,
        })
    assert response.status_code == 422
    assert "Please select two different conditions." in response.text
    with pytest.raises(ValueError, match="Please select two different conditions"):
        st._volcano_dataframe(
            kind="protein", condition1="A", condition2="A", identifier="workflow",
            p_value_threshold=.05, log2fc_threshold=1, test_type=method, use_uncorrected=False,
            frame_override=pd.DataFrame(), metadata_override=pd.DataFrame(),
        )
    with pytest.raises(ValueError, match="Please select two different conditions"):
        nb.volcano_data_f(pd.DataFrame(), pd.DataFrame(), "A", "A", test_type=method)


def _frame(n: int = 2000) -> pd.DataFrame:
    rng = np.random.default_rng(17)
    base = rng.normal(22, 2, n)
    frame = pd.DataFrame({c: base + rng.normal(0, 0.45, n) for c in SAMPLES})
    frame.iloc[:150, REPLICATES:] += 2.0
    for index in FLOOR_ROWS:
        frame.iloc[index, :REPLICATES] = 14.00
        frame.iloc[index, REPLICATES:] = 14.05
    frame.insert(0, "ProteinNames", [f"P{i}" for i in range(n)])
    return frame


def _volcano(frame: pd.DataFrame) -> pd.DataFrame:
    with patch.object(st, "_stats_source", return_value=("filtered", frame, METADATA, [])):
        return st._volcano_dataframe(
            kind="protein",
            condition1="A",
            condition2="B",
            identifier="workflow",
            p_value_threshold=0.05,
            log2fc_threshold=1.0,
            test_type="unpaired",
            use_uncorrected=False,
            data_source="data",
        )[2]


def test_identical_values_are_detected_whatever_their_binary_representation() -> None:
    values = np.array([
        [14.0, 14.0, 14.0],
        [14.05, 14.05, 14.05],
        [0.1 + 0.2, 0.1 + 0.2, 0.1 + 0.2],
        [14.0, 14.0, 14.1],
        [20.1, 20.4, 19.8],
    ])
    assert constant_within_group(values).tolist() == [True, True, True, False, False]
    variances = np.nanvar(values, axis=1, ddof=1)
    assert variances[1] != 0.0, "the fixture must keep its non-representable case"


def test_missing_values_do_not_make_a_group_look_constant() -> None:
    values = np.array([[14.0, np.nan, 14.0], [14.0, np.nan, 15.0]])
    assert constant_within_group(values).tolist() == [True, False]


def test_a_row_with_no_observations_is_not_flagged() -> None:
    values = np.array([[np.nan, np.nan, np.nan]])
    assert constant_within_group(values).tolist() == [False]


def test_the_floor_rows_are_flagged_and_nothing_else_is() -> None:
    result = _volcano(_frame())
    flagged = set(result.loc[result["zero_variance"], "ProteinNames"])
    assert flagged == {f"P{i}" for i in FLOOR_ROWS}


def test_genuine_effects_are_not_flagged() -> None:
    result = _volcano(_frame())
    genuine = result[result["ProteinNames"].isin([f"P{i}" for i in range(150)])]
    assert int(genuine["zero_variance"].sum()) == 0


def test_rows_without_any_variation_get_no_p_value() -> None:
    """Both groups constant: the standard error is zero, so the test is undefined.

    These rows used to get p ~ 0 and rank first on a fold change of 0.05.
    """
    result = _volcano(_frame())
    floor = result["ProteinNames"].isin([f"P{i}" for i in FLOOR_ROWS])
    assert result.loc[floor, "pval"].isna().all()
    assert result.loc[floor, "adj_pval"].isna().all()
    assert (result.loc[floor, "significance"] == "Unavailable").all()
    assert result.loc[~floor, "pval"].notna().all()
    top = result.nsmallest(12, "adj_pval")
    assert not top["zero_variance"].any()


def test_rows_without_variation_are_reported_in_the_gui_warnings() -> None:
    with patch.object(st, "_stats_source", return_value=("filtered", _frame(), METADATA, [])):
        warnings = st._volcano_dataframe(
            kind="protein", condition1="A", condition2="B", identifier="workflow",
            p_value_threshold=0.05, log2fc_threshold=1.0, test_type="unpaired",
            use_uncorrected=False, data_source="data",
        )[3]
    assert any(w.startswith(f"{len(FLOOR_ROWS)} rows have no variation") for w in warnings)


@pytest.mark.parametrize("column", ["log2FC", "significance"])
def test_existing_columns_are_untouched(column: str) -> None:
    result = _volcano(_frame())
    assert column in result.columns
    assert result[column].notna().all()


def test_paired_flag_looks_at_the_differences() -> None:
    """Differences of (-2, -2, -2) have no variation even though both groups vary."""
    frame = pd.DataFrame({"ProteinNames": ["shifted"], "A_0": [10.0], "A_1": [11.0], "A_2": [12.3],
                          "B_0": [12.0], "B_1": [13.0], "B_2": [14.3]})
    meta = METADATA.assign(pair_id=[1, 2, 3, 1, 2, 3])
    with patch.object(st, "_stats_source", return_value=("filtered", frame, meta, [])):
        result = st._volcano_dataframe(
            kind="protein", condition1="A", condition2="B", identifier="workflow",
            p_value_threshold=.05, log2fc_threshold=1, test_type="paired",
            use_uncorrected=False, data_source="data",
        )[2]
    assert bool(result.loc[0, "zero_variance"]) is True
    assert np.isnan(result.loc[0, "pval"]) and result.loc[0, "significance"] == "Unavailable"
    from proteomicscopylot.notebook_functions import volcano_data_f
    notebook = volcano_data_f(frame, meta, "A", "B", test_type="paired")
    assert bool(notebook.loc[0, "zero_variance"]) is True and np.isnan(notebook.loc[0, "pval"])


@pytest.mark.parametrize("test_type", ["unpaired", "unpaired_welch", "paired"])
@pytest.mark.parametrize("with_controls", [False, True])
def test_degenerate_tests_match_scipy_and_preserve_missing_results(test_type, with_controls):
    from scipy import stats
    from proteomicscopylot.notebook_functions import volcano_data_f, volcano_data_f_control

    a = np.array([[10, 10, 10], [10, 10, 10], [10, 10, 10], [10, 11, 13]])
    b = np.array([[12, 12, 12], [10, 10, 10], [10, 12, 14], [12, 15, 13]])
    frame = pd.DataFrame(np.column_stack([a, b]), columns=SAMPLES)
    frame.insert(0, "ProteinNames", ["different", "identical", "one_constant", "variable"])
    meta = METADATA.assign(pair_id=[1, 2, 3, 1, 2, 3])
    controls = {}
    if with_controls:
        for group in ["CA", "CB"]:
            samples = [f"{group}_{i}" for i in range(3)]
            frame[samples] = 10.0
            meta = pd.concat([meta, pd.DataFrame({"sample": samples, "condition": group, "pair_id": [1,2,3]})])
        controls = {"condition1_control": "CA", "condition2_control": "CB"}
    with patch.object(st, "_stats_source", return_value=("filtered", frame, meta, [])):
        result = st._volcano_dataframe(
            kind="protein", condition1="A", condition2="B", identifier="workflow",
            p_value_threshold=.05, log2fc_threshold=1, test_type=test_type,
            use_uncorrected=False, data_source="data", **controls,
        )[2]
    scipy_expected = (stats.ttest_rel(b, a, axis=1) if test_type == "paired" else
                      stats.ttest_ind(b, a, axis=1, equal_var=test_type == "unpaired" and not with_controls)).pvalue
    # Rows 0 and 1 have no variation in any group (paired: constant differences):
    # no p-value, where scipy reports 0 and NaN.
    expected = scipy_expected.copy()
    expected[:2] = np.nan
    np.testing.assert_allclose(result.pval, expected, equal_nan=True)
    notebook_function = volcano_data_f_control if with_controls else volcano_data_f
    notebook = notebook_function(frame, meta, "A", "B", test_type=test_type, **controls)
    np.testing.assert_allclose(notebook.pval, expected, equal_nan=True)
    finite = np.isfinite(expected)
    adjusted = stats.false_discovery_control(expected[finite])
    np.testing.assert_allclose(result.adj_pval[finite], adjusted)
    np.testing.assert_allclose(notebook.adj_pval[finite], adjusted)
    assert (result.significance.iloc[:2] == "Unavailable").all()
    assert (notebook.significance.iloc[:2] == "Unavailable").all()
    assert np.isnan(result.adj_pval.iloc[1])
    response = st._volcano_response("protein", "filtered", "ProteinNames", result, [])
    assert response.rows[1]["pval"] is None
    assert response.rows[1]["adj_pval"] is None
    assert 'NaN' not in response.model_dump_json()
    figure = st._volcano_figure(
        result, label_column="ProteinNames", condition1="A", condition2="B",
        p_value_threshold=.05, log2fc_threshold=1, use_uncorrected=False, highlight_terms=[],
    )
    plotted_y = [value for trace in figure.data for value in trace.y]
    assert len(plotted_y) == 2
    assert np.isfinite(plotted_y).all()
    if not with_controls and test_type != "paired":
        from app.schemas.stats import SimulationRequest
        payload = SimulationRequest(kind="protein", condition1="A", condition2="B",
                                    testType=test_type, useUncorrected=False)
        with patch.object(st, "_stats_source", return_value=("filtered", frame, meta, [])):
            simulated = st.run_simulation(payload)
        # The projection keeps the plain t-test arithmetic, but at the observed
        # n it reproduces the volcano: rows without variation get no p-value
        # there either, so the BH family (and every other row's adjusted p) agree.
        np.testing.assert_allclose(
            [row["pval"] if row["pval"] is not None else np.nan for row in simulated.rows],
            expected, equal_nan=True,
        )
        np.testing.assert_allclose(
            [row["adj_pval"] if row["adj_pval"] is not None else np.nan for row in simulated.rows],
            result.adj_pval.to_numpy(), equal_nan=True,
        )
        for index in (0, 1):
            assert simulated.rows[index]["significance"] == "Unavailable"
            assert simulated.rows[index]["adj_pval"] is None
        assert any("no variation in either compared group" in w for w in simulated.warnings)


@pytest.mark.requires_r()
def test_r_notebook_zero_standard_error_convention():
    """R gives rows without variation no p-value, like the app and pip."""
    import subprocess
    from app.services.r_runtime import detect_r_runtime

    runtime = detect_r_runtime()
    script = r'''
      source("proteomicscopylot/notebook_functions.R")
      d <- data.frame(ProteinNames=c("different", "identical", "one_constant", "variable"),
        A_0=c(10,10,10,10), A_1=c(10,10,10,11), A_2=c(10,10,10,13),
        B_0=c(12,10,10,12), B_1=c(12,10,12,15), B_2=c(12,10,14,13))
      m <- data.frame(sample=names(d)[-1], condition=rep(c("A","B"),each=3), pair_id=rep(1:3,2))
      for (group in c("CA","CB")) {
        samples <- paste0(group,"_",0:2)
        d[samples] <- 10
        m <- rbind(m,data.frame(sample=samples,condition=group,pair_id=1:3))
      }
      for (design in c("unpaired","unpaired_welch","paired")) for (controls in c(FALSE,TRUE)) {
        out <- if (controls) volcano_data_f_control(d,m,"A","B","CA","CB",test_type=design) else
          volcano_data_f(d,m,"A","B",test_type=design)
        stopifnot(is.na(out$pval[1]), is.na(out$pval[2]), is.na(out$adj_pval[2]),
          all(is.finite(out$pval[c(3,4)])), all(out$significance[1:2] == "Unavailable"),
          isTRUE(all.equal(out$adj_pval[c(3,4)],p.adjust(out$pval[c(3,4)],"BH"))))
      }
    '''
    result = subprocess.run([runtime["executable"], "-e", script], cwd=ROOT,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


def test_bh_preserves_an_entirely_unavailable_family():
    from proteomicscopylot.notebook_functions import _adjust_finite_pvalues

    for adjust in [st._bh_adjust, _adjust_finite_pvalues]:
        assert np.isnan(adjust(np.array([np.nan, np.nan]))).all()
        assert adjust(np.array([])).size == 0
