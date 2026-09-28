"""The arithmetic every differential test in the backend shares.

Benjamini-Hochberg, the pooled two-sample standard error, Welch-Satterthwaite
for a sum of independent group means, and the two-sided t p-value. The
volcano, the control volcano, the replicate & variance projection and the
paired test all used to carry their own copy of these lines; one copy means
one place to verify against scipy/statsmodels (tests/backend/test_stats_core.py).

The pip package (`proteomicscopylot/notebook_functions.py`) keeps its own
implementation on purpose: it must install and run without the backend, and
the cross-implementation tests prove the two agree numerically.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import t as _student_t


def bh_adjust(pvalues: np.ndarray) -> np.ndarray:
    """Benjamini-Hochberg adjusted p-values; NaN in, NaN out, others adjusted among themselves."""
    pvalues = np.asarray(pvalues, dtype=float)
    if pvalues.size == 0:
        return pvalues
    finite = np.isfinite(pvalues)
    if not finite.all():
        result = np.full(pvalues.shape, np.nan)
        result[finite] = bh_adjust(pvalues[finite])
        return result
    order = np.argsort(pvalues)
    ranked = pvalues[order]
    n = float(len(ranked))
    adjusted_ranked = ranked * n / np.arange(1.0, n + 1.0)
    adjusted_ranked = np.minimum.accumulate(adjusted_ranked[::-1])[::-1]
    adjusted = np.empty_like(adjusted_ranked)
    adjusted[order] = np.clip(adjusted_ranked, 0.0, 1.0)
    return adjusted


def satterthwaite(components: list[tuple[np.ndarray, np.ndarray]]) -> tuple[np.ndarray, np.ndarray]:
    """Standard error and Welch-Satterthwaite degrees of freedom for a sum of group means.

    Each component is (variance, n) for one independent group. Used instead of
    pooling whenever the groups need not share a variance -- Welch's test, and
    every control-normalised comparison, where the control means add their own
    uncertainty.
    """
    ratios = [np.asarray(variance, dtype=float) / np.asarray(count, dtype=float) for variance, count in components]
    se_squared = np.sum(ratios, axis=0)
    denominator = np.sum(
        [ratio**2 / np.maximum(np.asarray(count, dtype=float) - 1.0, 1e-12) for ratio, (_, count) in zip(ratios, components)],
        axis=0,
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        dof = se_squared**2 / denominator
    dof = np.where(se_squared == 0, 1.0, dof)
    return np.sqrt(se_squared), dof


def pooled_se_df(var1, n1, var2, n2) -> tuple[np.ndarray, np.ndarray]:
    """Student's pooled-variance standard error and n1 + n2 - 2 degrees of freedom."""
    var1 = np.asarray(var1, dtype=float)
    var2 = np.asarray(var2, dtype=float)
    n1 = np.asarray(n1, dtype=float)
    n2 = np.asarray(n2, dtype=float)
    pooled_var = ((n1 - 1.0) * var1 + (n2 - 1.0) * var2) / (n1 + n2 - 2.0)
    se = np.sqrt(pooled_var * (1.0 / n1 + 1.0 / n2))
    return se, n1 + n2 - 2.0


def two_sided_t_pvalues(estimate, se, dof) -> np.ndarray:
    """Two-sided p-values of estimate / se on `dof` degrees of freedom."""
    with np.errstate(divide="ignore", invalid="ignore"):
        t_stat = np.asarray(estimate, dtype=float) / np.asarray(se, dtype=float)
    return np.asarray(2.0 * _student_t.sf(np.abs(t_stat), dof), dtype=float)
