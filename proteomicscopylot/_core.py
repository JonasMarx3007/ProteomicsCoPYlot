"""The plotting-free arithmetic the application and the pip package share.

One copy, imported by `backend/app/services/functions.py` and `stats_core.py`
(through `app.services.copylot_core`) and by `notebook_functions.py`, so these
results cannot drift apart between the two Python pipelines. Notebook exports
stay self-contained: the export inlines the definitions it needs in place of the
import block (`notebook_qc._source`). The R functions keep their own copy,
checked by the cross-implementation tests.

Only numpy, pandas, scipy and the standard library: nothing here may import the
application or a plotting library.
"""
from __future__ import annotations

import re
import warnings

import numpy as np
import pandas as pd
from scipy.stats import t as _student_t

_SAMPLE_DOTTED_SUFFIX = re.compile(
    r"(?:(?:\.(?:PG|GG|EG|FG|PEP|PR|Precursor|Protein|Peptide))?\."
    r"(?:(?:Avg|Average)?Log[._\s-]*2(?:Normal(?:i[sz]ed|isation|ization))?"
    r"(?:Quantity|Intensity|Abundance)|Normal(?:i[sz]ed|isation|ization)"
    r"(?:Quantity|Intensity|Abundance)?|Max[._\s-]*LFQ(?:Quantity|Intensity|Abundance)?|"
    r"TotalQuantity|Quantity|Intensity|Abundance))$",
    re.IGNORECASE,
)
_SAMPLE_TEXT_SUFFIX = re.compile(
    r"[\s._-]+(?:(?:Max[\s._-]*LFQ[\s._-]+)?"
    r"(?:Unique[\s._-]+|Total[\s._-]+|Razor[\s._-]+)?Intensity|"
    r"(?:Unique[\s._-]+|Total[\s._-]+|Razor[\s._-]+)?Spectral[\s._-]+Count|"
    r"PSMs?|Percent[\s._-]+PSMs?|LFQ[\s._-]+Intensity|iBAQ|"
    r"MS\s*/\s*MS[\s._-]+Count|MS[12][\s._-]+(?:Intensity|Count)|"
    r"Razor\s*\+\s*Unique[\s._-]+Peptides|Unique[\s._-]+Peptides|Peptides|"
    r"Sequence[\s._-]+Coverage(?:[\s._-]*\[%\])?|"
    r"Log[._\s-]*2[\s._-]*(?:Quantity|Intensity|Abundance|Ratio)|"
    r"(?:Quantity|Abundance|Ratio))$",
    re.IGNORECASE,
)
_SAMPLE_ACQUISITION_SUFFIX = re.compile(r"\.(?:d|htrms|raw|wiff2?|mzml|mzxml)$", re.IGNORECASE)
_SAMPLE_NUMBER = re.compile(r"\d+")


# --- sample names ---------------------------------------------------------------

def strip_sample_measurement_suffix(value):
    sample = re.split(r"[\\/]", str(value).strip())[-1]
    previous = None
    while sample != previous:
        previous = sample
        sample = _SAMPLE_DOTTED_SUFFIX.sub("", sample).rstrip()
        sample = _SAMPLE_TEXT_SUFFIX.sub("", sample).rstrip()
    return _SAMPLE_ACQUISITION_SUFFIX.sub("", sample).rstrip()


def extract_sample_id(value):
    original = str(value).strip()
    numbers = _SAMPLE_NUMBER.findall(strip_sample_measurement_suffix(original))
    return numbers[-1] if numbers else original


def _significance_pval_column(table):
    """The p-value column significance is called on: `selected_pval`, or `adj_pval` in older tables."""
    for column in ("selected_pval", "adj_pval"):
        if column in table.columns:
            return column
    return None


def constant_within_group(values):
    """True per row where every observed replicate in the group holds one value.

    Such a row has no measured within-group variation, so the standard error
    collapses and the t-statistic explodes: a fold change of 0.05 can reach
    p = 2e-54 and outrank every genuine effect at the top of a volcano. The
    p-value itself is correct and matches `scipy.stats.ttest_ind`; what the flag
    marks is that the significance comes from absent variation rather than
    effect size. Values reported at a detection floor, rounded exports and
    imputation filling one value across replicates all produce it.

    Tested with min == max rather than variance == 0, which is exact regardless
    of floating-point representation: 14.05 repeated three times has a variance
    of 4.7e-30, not 0, so a zero test would miss it.
    """
    numeric = np.asarray(values, dtype=float)
    observed = np.isfinite(numeric)
    counts = observed.sum(axis=1)
    masked = np.where(observed, numeric, np.nan)
    with warnings.catch_warnings():
        # A row with nothing observed is an all-NaN slice; numpy warns and
        # returns NaN, and the count check below already excludes it.
        warnings.simplefilter("ignore", RuntimeWarning)
        low = np.nanmin(masked, axis=1)
        high = np.nanmax(masked, axis=1)
    return (counts > 0) & (low == high)


def condition_mean(data, columns, min_present=1):
    """Mean across a condition's replicates, blanked where too few were observed.

    `mean(axis=1)` skips missing values silently, so a condition mean resting on
    one replicate is plotted and correlated at the same weight as a fully
    observed one. Measured on 2000 features with 30% poor coverage, the
    single-replicate means were off by 0.28 log2 on average and 1.21 at worst
    against the same features' fully observed means.

    `min_present` is the smallest number of observations a mean may rest on. The
    default of 1 reports every mean, which is the long-standing behaviour and keeps
    previously generated results reproducible. Pass 2 or more to require that a
    mean rest on enough replicates to carry spread information.

    Returns (means, counts) so the caller can report how many features were
    excluded rather than dropping them silently.
    """
    numeric = data[list(columns)].apply(pd.to_numeric, errors="coerce")
    counts = numeric.notna().sum(axis=1)
    means = numeric.mean(axis=1)
    return means.where(counts >= int(min_present)), counts


def resolve_feature_scaling(scaling="auto", method="PCA"):
    """How features are weighted before a projection.

    ``centered`` subtracts each feature's mean across samples and stops there,
    so a feature contributes in proportion to its variance. ``unit_variance``
    also divides by the standard deviation, giving every feature equal weight.

    ``auto`` keeps each method's established default: PCA on the centred matrix,
    UMAP and t-SNE on unit-variance features because both read distances and are
    sensitive to feature scale. The two answer different questions, so a run that
    mixes them without saying which was used is not reproducible.
    """
    requested = str(scaling or "auto").strip().lower()
    if requested in {"centered", "centred"}:
        return "centered"
    if requested in {"unit_variance", "scaled"}:
        return "unit_variance"
    if requested != "auto":
        raise ValueError(
            "Unsupported scaling. Choose 'auto', 'centered', or 'unit_variance'."
        )
    return "centered" if str(method or "PCA").strip().lower() == "pca" else "unit_variance"


def _auto_label_col(frame: pd.DataFrame) -> str:
    if "Phosphoprotein" in frame.columns:
        return "Phosphoprotein"
    if "ProteinNames" in frame.columns:
        return "ProteinNames"
    if "PTM_Collapse_key" in frame.columns:
        return "PTM_Collapse_key"
    if "Gene_group" in frame.columns:
        return "Gene_group"
    if "GeneNames" in frame.columns:
        return "GeneNames"
    raise ValueError("No supported label column was found.")


# --- the arithmetic every differential test shares --------------------------------

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
