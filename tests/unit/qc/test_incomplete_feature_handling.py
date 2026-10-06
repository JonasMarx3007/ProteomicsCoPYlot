"""Incomplete features are dropped and reported, not allowed to block the plot.

Clustering and projection are undefined for a feature missing in any sample.
The tool used to refuse the whole request, which on the bundled HEK293 data cost
the entire protein ANOVA heatmap for 27 features out of 2,908 -- and recommended
disabling clustering, which the interface offers no way to do. The rule now is:
drop them, and say how many directly beneath the plot.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]

from app.schemas.stats import AnovaRequest
from app.services.clustering_tools import (
    CompletenessReport,
    completeness_message,
    drop_incomplete_features,
)
from app.services.stats_tools import _anova_cluster_dataframe


def _matrix(rows=10, cols=4, missing=()):
    data = np.arange(rows * cols, dtype=float).reshape(rows, cols)
    for row, col in missing:
        data[row, col] = np.nan
    return data


def _report(dropped, total):
    return CompletenessReport(kept=np.ones(total, dtype=bool), dropped=dropped, total=total)


def test_a_complete_matrix_is_untouched() -> None:
    matrix, report = drop_incomplete_features(_matrix())
    assert matrix.shape == (10, 4)
    assert not report.any_dropped
    assert completeness_message(report) is None


def test_incomplete_rows_are_dropped_not_refused() -> None:
    matrix, report = drop_incomplete_features(_matrix(missing=[(2, 1), (7, 3)]))
    assert matrix.shape == (8, 4), "the other eight features should still be clustered"
    assert report.dropped == 2 and report.total == 10
    assert np.isfinite(matrix).all()


def test_the_kept_mask_selects_the_surviving_rows() -> None:
    """Callers use the mask to keep their frame aligned with the matrix."""
    _, report = drop_incomplete_features(_matrix(missing=[(0, 0), (4, 2)]))
    assert list(np.flatnonzero(~report.kept)) == [0, 4]


def test_nothing_usable_left_is_still_an_error() -> None:
    every_row = [(row, 0) for row in range(10)]
    with pytest.raises(ValueError, match="only 0 of 10 features are observed"):
        drop_incomplete_features(_matrix(missing=every_row), context="ANOVA clustering")


def test_infinities_count_as_missing() -> None:
    data = _matrix()
    data[3, 2] = np.inf
    _, report = drop_incomplete_features(data)
    assert report.dropped == 1


@pytest.mark.parametrize(
    "dropped,total,expected",
    [
        (27, 2908, "0.9% of proteins dropped for clustering (27 of 2,908)"),
        (162, 759, "21% of phosphosites dropped for clustering (162 of 759)"),
        (1, 100000, "<0.1% of proteins dropped for clustering (1 of 100,000)"),
    ],
)
def test_the_message_states_the_scope(dropped, total, expected) -> None:
    noun = "phosphosites" if "phosphosite" in expected else "proteins"
    message = completeness_message(_report(dropped, total), noun=noun)
    assert message.startswith(expected)
    assert "not observed in every sample" in message


def test_a_nonzero_drop_never_reports_zero_percent() -> None:
    """'0% dropped' next to a real exclusion is worse than saying nothing."""
    message = completeness_message(_report(1, 1_000_000), noun="proteins")
    assert "0%" not in message.split("of")[0] or "<0.1%" in message


def test_anova_clustering_drops_and_reports(monkeypatch) -> None:
    samples = [f"{c}_{i}" for c in ("A", "B") for i in (1, 2, 3)]
    rng = np.random.default_rng(3)
    frame = pd.DataFrame(rng.normal(20, 1, (40, len(samples))), columns=samples)
    frame.insert(0, "ProteinNames", [f"P{i}" for i in range(40)])
    frame["adj_pval"] = 0.001
    frame.loc[0:3, samples[0]] = np.nan  # four incomplete features
    metadata = pd.DataFrame(
        {"sample": samples, "condition": [c for c in ("A", "B") for _ in range(3)]}
    )

    clustered, report = _anova_cluster_dataframe(
        frame, metadata, AnovaRequest(kind="protein", source="anova_cluster", nClusters=2)
    )
    assert len(clustered) == 36, "clustering should proceed on the complete features"
    assert report is not None and report.dropped == 4
    message = completeness_message(report, noun="proteins")
    assert "4 of 40" in message


def test_the_notebook_packages_word_it_the_same_way() -> None:
    """One rule should read identically in the app and in a notebook."""
    from proteomicscopylot.notebook_functions import _dropped_features_message

    app = completeness_message(_report(27, 2908), noun="features")
    notebook = _dropped_features_message(27, 2908)
    assert app == notebook, f"\n app: {app}\n pip: {notebook}"


def test_the_notebook_package_warns_under_the_cell() -> None:
    """A notebook has no plot footer, so the warning is the equivalent surface."""
    from proteomicscopylot.notebook_functions import _warn_dropped_features

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _warn_dropped_features(27, 2908)
    assert len(caught) == 1
    assert "27 of 2,908" in str(caught[0].message)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _warn_dropped_features(0, 2908)
    assert not caught, "nothing dropped should not warn"


def test_the_notebook_package_drops_the_same_rows() -> None:
    from proteomicscopylot.notebook_functions import _drop_incomplete_features

    data = _matrix(missing=[(2, 1), (7, 3)])
    app_matrix, app_report = drop_incomplete_features(data.copy())
    pip_matrix, pip_kept, pip_dropped, pip_total = _drop_incomplete_features(data.copy())
    assert np.array_equal(app_matrix, pip_matrix)
    assert list(app_report.kept) == list(pip_kept)
    assert (app_report.dropped, app_report.total) == (pip_dropped, pip_total)
