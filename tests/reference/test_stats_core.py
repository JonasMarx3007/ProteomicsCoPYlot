"""stats_core against scipy and statsmodels: the one copy the backend tests share."""

from __future__ import annotations

import numpy as np
from scipy import stats

from app.services.stats_core import bh_adjust, pooled_se_df, satterthwaite, two_sided_t_pvalues


def test_bh_matches_statsmodels_and_keeps_nans():
    from statsmodels.stats import multitest as statsmodels
    rng = np.random.default_rng(1)
    p = np.concatenate([rng.uniform(0, 0.01, 6), rng.uniform(0, 1, 40)])
    assert np.allclose(bh_adjust(p), statsmodels.multipletests(p, method="fdr_bh")[1], rtol=1e-12)
    with_nan = p.copy()
    with_nan[[3, 20]] = np.nan
    adjusted = bh_adjust(with_nan)
    assert np.isnan(adjusted[[3, 20]]).all()
    finite = ~np.isnan(with_nan)
    assert np.allclose(adjusted[finite], statsmodels.multipletests(with_nan[finite], method="fdr_bh")[1])
    assert bh_adjust(np.array([])).size == 0


def test_pooled_and_welch_match_scipy():
    rng = np.random.default_rng(2)
    x = rng.normal(0, 1, (50, 4))
    y = rng.normal(0.5, 2, (50, 6))
    var1, var2 = x.var(axis=1, ddof=1), y.var(axis=1, ddof=1)
    n1, n2 = np.full(50, 4.0), np.full(50, 6.0)
    diff = x.mean(axis=1) - y.mean(axis=1)

    se, dof = pooled_se_df(var1, n1, var2, n2)
    assert np.allclose(two_sided_t_pvalues(diff, se, dof), stats.ttest_ind(x, y, axis=1).pvalue, rtol=1e-10)
    assert np.allclose(dof, 8.0)

    se, dof = satterthwaite([(var1, n1), (var2, n2)])
    welch = stats.ttest_ind(x, y, axis=1, equal_var=False)
    assert np.allclose(two_sided_t_pvalues(diff, se, dof), welch.pvalue, rtol=1e-10)
    assert np.allclose(dof, welch.df, rtol=1e-10)


def test_zero_variance_rows_do_not_raise():
    se, dof = satterthwaite([(np.zeros(3), np.full(3, 3.0)), (np.zeros(3), np.full(3, 3.0))])
    assert np.all(se == 0) and np.all(dof == 1.0)
    p = two_sided_t_pvalues(np.array([0.0, 1.0, -1.0]), se, dof)
    assert np.isnan(p[0]) and p[1] == 0.0 and p[2] == 0.0
