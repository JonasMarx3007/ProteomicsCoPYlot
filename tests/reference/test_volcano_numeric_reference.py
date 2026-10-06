from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy import stats as scipy_stats
from statsmodels.stats.multitest import multipletests

ROOT = Path(__file__).resolve().parents[2]

from app.services.annotation_store import get_annotation
from app.schemas.stats import AnovaRequest
from app.services.stats_tools import _anova_dataframe, _volcano_dataframe
from app.services.viewer_bootstrap import load_viewer_state

KIND = "protein"
C1, C2 = "WT", "GRK"


@pytest.fixture(scope="module")
def loaded(example_project):
    annotation = get_annotation(KIND)
    return annotation.filtered_data, annotation.metadata


def _columns(metadata, condition):
    return [
        str(s) for s, c in zip(metadata["sample"], metadata["condition"]) if c == condition
    ]


LABEL = "ProteinNames"


def _reference(frame, metadata):
    """Independent log2FC and p per feature, keyed by identifier.

    Keyed rather than positional: the volcano drops features that lack two
    observations in a group, so the two frames do not line up by row.
    """
    a = frame[_columns(metadata, C1)].apply(lambda c: c.map(float)).to_numpy()
    b = frame[_columns(metadata, C2)].apply(lambda c: c.map(float)).to_numpy()
    _, pvalue = scipy_stats.ttest_ind(b, a, axis=1, nan_policy="omit", equal_var=True)
    return pd.DataFrame({
        LABEL: frame[LABEL].astype(str).to_numpy(),
        "ref_log2FC": np.nanmean(a, axis=1) - np.nanmean(b, axis=1),
        "ref_pval": np.asarray(pvalue, dtype=float),
    })


def _volcano():
    # returns (source_used, label_column, frame, warnings)
    return _volcano_dataframe(
        kind=KIND, condition1=C1, condition2=C2, identifier="workflow",
        p_value_threshold=0.05, log2fc_threshold=1.0,
        test_type="unpaired", use_uncorrected=False,
    )[2]


def test_the_fold_change_is_condition1_minus_condition2(loaded) -> None:
    """The direction of the volcano, asserted on its own.

    Inverting this sign turns every upregulated protein into a downregulated one
    and changes the biological conclusion of every figure the tool produces. It
    is the single most consequential thing the volcano can get wrong, so it is
    checked here rather than left to a golden string in an unrelated test.
    """
    frame, metadata = loaded
    merged = _volcano().merge(_reference(frame, metadata), on=LABEL)
    observed = merged["log2FC"].to_numpy(dtype=float)
    reference = merged["ref_log2FC"].to_numpy(dtype=float)
    both = np.isfinite(observed) & np.isfinite(reference)
    assert both.sum() > 1000, f"only {both.sum()} features aligned"

    worst = float(np.max(np.abs(observed[both] - reference[both])))
    assert worst < 1e-9, (
        f"the reported fold change differs from condition1 - condition2 by {worst:.3e}; "
        "a sign inversion here would flip every call in every figure"
    )


def test_the_p_values_match_an_independent_t_test(loaded) -> None:
    frame, metadata = loaded
    merged = _volcano().merge(_reference(frame, metadata), on=LABEL)
    observed = merged["pval"].to_numpy(dtype=float)
    reference = merged["ref_pval"].to_numpy(dtype=float)
    both = np.isfinite(observed) & np.isfinite(reference)
    worst = float(np.max(np.abs(observed[both] - reference[both])))
    assert worst < 1e-9, f"volcano p-values differ from scipy ttest_ind by {worst:.3e}"


def test_the_adjusted_p_values_are_benjamini_hochberg_not_bonferroni(loaded) -> None:
    """The correction is asserted by value, not by the label the output carries.

    A table that says "Benjamini-Hochberg" while applying Bonferroni satisfies
    every test that checks only the string, and changes thousands of calls.
    """
    result = _volcano()
    raw = result["pval"].to_numpy(dtype=float)
    usable = np.isfinite(raw)
    expected_bh = multipletests(raw[usable], method="fdr_bh")[1]
    expected_bonferroni = multipletests(raw[usable], method="bonferroni")[1]
    observed = result["adj_pval"].to_numpy(dtype=float)[usable]

    assert np.allclose(observed, expected_bh, rtol=1e-9, atol=1e-12)
    assert not np.allclose(observed, expected_bonferroni, rtol=1e-3), (
        "the adjusted p-values are indistinguishable from Bonferroni"
    )


def test_anova_adjusted_p_values_are_benjamini_hochberg_not_bonferroni(loaded) -> None:
    """ANOVA had no reference test of its own; swapping its correction was invisible."""
    # 2026-10-02: the app's ANOVA path, not the unused functions.py copy it replaced.
    result = _anova_dataframe(AnovaRequest(kind=KIND))[2]
    raw = result["pval"].to_numpy(dtype=float)
    usable = np.isfinite(raw)
    observed = result["adj_pval"].to_numpy(dtype=float)[usable]

    assert np.allclose(observed, multipletests(raw[usable], method="fdr_bh")[1], rtol=1e-9)
    assert not np.allclose(
        observed, multipletests(raw[usable], method="bonferroni")[1], rtol=1e-3
    ), "the ANOVA table's adjusted p-values are indistinguishable from Bonferroni"
