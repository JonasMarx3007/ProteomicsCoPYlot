from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]

from app.schemas.stats import AnovaRequest
from app.services import stats_tools as st
from app.services.runtime_cache import invalidate_runtime_cache


@pytest.fixture(autouse=True)
def _isolate_runtime_cache():
    invalidate_runtime_cache("test")
    yield
    invalidate_runtime_cache("test")

REPS = 4
CONDITIONS = ("A", "B", "C", "D")
SAMPLES = [f"{c}_{i}" for c in CONDITIONS for i in range(REPS)]
METADATA = pd.DataFrame(
    {"sample": SAMPLES, "condition": [c for c in CONDITIONS for _ in range(REPS)]}
)


def _frame(n: int = 120, *, conditions=CONDITIONS, missing_at=None) -> pd.DataFrame:
    rng = np.random.default_rng(2)
    samples = [f"{c}_{i}" for c in conditions for i in range(REPS)]
    frame = pd.DataFrame(rng.normal(20, 1.0, (n, len(samples))), columns=samples)
    frame.iloc[: n // 4, -REPS:] += 3.0
    frame.insert(0, "ProteinNames", [f"P{i}" for i in range(n)])
    frame.insert(1, "GeneNames", [f"G{i}" for i in range(n)])
    if missing_at is not None:
        frame.iloc[missing_at, 2] = np.nan
    return frame


def _metadata(conditions=CONDITIONS) -> pd.DataFrame:
    samples = [f"{c}_{i}" for c in conditions for i in range(REPS)]
    return pd.DataFrame(
        {"sample": samples, "condition": [c for c in conditions for _ in range(REPS)]}
    )


def _run(frame: pd.DataFrame, metadata: pd.DataFrame, **kwargs):
    payload = AnovaRequest(kind="protein", dataSource="data", **kwargs)
    with patch.object(st, "_stats_source", return_value=("filtered", frame, metadata, [])):
        return st.run_anova(payload)


@pytest.fixture(scope="module")
def tukey():
    return _run(_frame(), METADATA, postHoc="tukey")


def test_post_hoc_is_off_by_default() -> None:
    result = _run(_frame(), METADATA)
    assert result.postHocMethod is None
    assert result.postHocRows == []
    assert result.postHocSignificantCount == 0


def test_requesting_tukey_names_the_method() -> None:
    result = _run(_frame(), METADATA, postHoc="tukey")
    assert result.postHocMethod == "Tukey HSD"
    assert result.postHocRows


def test_the_omnibus_result_is_unchanged_by_asking_for_post_hoc() -> None:
    plain = _run(_frame(), METADATA)
    with_tukey = _run(_frame(), METADATA, postHoc="tukey")
    assert plain.rows == with_tukey.rows
    assert plain.significantCount == with_tukey.significantCount


def test_only_anova_significant_rows_get_a_post_hoc() -> None:
    result = _run(_frame(), METADATA, postHoc="tukey", pValueThreshold=0.05)
    n_pairs = len(CONDITIONS) * (len(CONDITIONS) - 1) // 2
    assert len(result.postHocRows) == result.significantCount * n_pairs

    tested = {row["ProteinNames"] for row in result.postHocRows}
    significant = {
        row["ProteinNames"] for row in result.rows if row["adj_pval"] < 0.05
    }
    assert tested == significant, "post-hoc ran on rows the omnibus F did not license"


def test_a_stricter_threshold_gates_more_rows_out() -> None:
    loose = _run(_frame(), METADATA, postHoc="tukey", pValueThreshold=0.05)
    strict = _run(_frame(), METADATA, postHoc="tukey", pValueThreshold=1e-8)
    assert len(strict.postHocRows) < len(loose.postHocRows)


def test_no_significant_rows_yields_no_post_hoc_and_says_so() -> None:
    result = _run(_frame(), METADATA, postHoc="tukey", pValueThreshold=1e-300)
    assert result.postHocRows == []
    assert any("Tukey" in w for w in result.warnings)
    assert any("No rows passed" in w for w in result.warnings)


def test_significant_constant_groups_do_not_report_no_anova_hits():
    frame = _frame(n=1)
    for index, condition in enumerate(CONDITIONS):
        frame[[f"{condition}_{i}" for i in range(REPS)]] = 10. + 2 * index
    result = _run(frame, METADATA, postHoc="tukey")
    assert result.significantCount == 1
    assert result.postHocRows == []
    assert any("no usable Tukey HSD comparisons" in w for w in result.warnings)
    assert not any("No rows passed" in w for w in result.warnings)


def test_two_conditions_skip_tukey_with_an_explanation() -> None:
    conditions = ("A", "B")
    result = _run(
        _frame(conditions=conditions), _metadata(conditions), postHoc="tukey"
    )
    assert result.postHocRows == []
    assert any("two conditions" in w for w in result.warnings)


@pytest.mark.parametrize("missing_at", [None, 5], ids=["equal-n", "unequal-n"])
def test_p_values_match_statsmodels(missing_at) -> None:
    statsmodels = pytest.importorskip("statsmodels.stats.multicomp")
    frame = _frame(missing_at=missing_at)
    result = _run(frame, METADATA, postHoc="tukey")
    post_hoc = pd.DataFrame(result.postHocRows)
    assert not post_hoc.empty

    worst = 0.0
    for label in post_hoc["ProteinNames"].drop_duplicates().head(4):
        row = frame[frame["ProteinNames"] == label].iloc[0]
        values, labels = [], []
        for condition in CONDITIONS:
            series = pd.to_numeric(
                row[[f"{condition}_{i}" for i in range(REPS)]], errors="coerce"
            ).dropna()
            values.extend(series.tolist())
            labels.extend([condition] * len(series))
        reference = statsmodels.pairwise_tukeyhsd(np.array(values), np.array(labels))
        pairs = reference._multicomp.pairindices
        expected = {
            frozenset(
                (reference.groupsunique[a], reference.groupsunique[b])
            ): p
            for a, b, p in zip(pairs[0], pairs[1], reference.pvalues)
        }
        for _, comparison in post_hoc[post_hoc["ProteinNames"] == label].iterrows():
            key = frozenset((comparison["group1"], comparison["group2"]))
            worst = max(worst, abs(comparison["tukey_pval"] - expected[key]))
    assert worst < 1e-12, f"max |p difference| vs statsmodels was {worst:.2e}"


def test_every_condition_pair_is_reported_once_per_feature(tukey) -> None:
    result = tukey
    post_hoc = pd.DataFrame(result.postHocRows)
    per_feature = post_hoc.groupby("ProteinNames")["comparison"].nunique()
    assert (per_feature == 6).all(), "expected all 6 pairs of 4 conditions"
    assert not post_hoc.duplicated(["ProteinNames", "comparison"]).any()


def test_the_table_carries_what_a_reader_needs(tukey) -> None:
    result = tukey
    columns = set(result.postHocRows[0])
    for required in (
        "comparison",
        "group1",
        "group2",
        "log2FC",
        "n_group1",
        "n_group2",
        "q_statistic",
        "tukey_pval",
        "significance",
        "anova_adj_pval",
    ):
        assert required in columns, f"post-hoc table is missing {required!r}"


def test_the_condition_that_really_differs_is_the_one_found(tukey) -> None:
    result = tukey
    post_hoc = pd.DataFrame(result.postHocRows)
    hits = post_hoc[post_hoc["significance"] == "Significant"]
    involves_d = hits.apply(lambda r: "D" in (r["group1"], r["group2"]), axis=1)
    assert involves_d.mean() > 0.9, "post-hoc did not localise the real effect"


def test_reported_fold_change_is_group1_minus_group2(tukey) -> None:
    result = tukey
    post_hoc = pd.DataFrame(result.postHocRows)
    row = post_hoc[
        (post_hoc["group1"] == "A") & (post_hoc["group2"] == "D")
    ].iloc[0]
    # D carries the injected +3 shift, so A - D must be negative.
    assert row["log2FC"] < 0, "sign convention should be group1 - group2"
