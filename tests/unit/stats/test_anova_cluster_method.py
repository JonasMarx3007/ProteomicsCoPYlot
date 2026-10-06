"""The ANOVA clustering linkage is selectable, and every path uses the same one.

Clustering happens in three places for one user action: the table, the heatmap,
and ORA's re-run to resolve a selected cluster. They must partition identically,
because the cluster *numbers* are how the user refers to a group.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]

from app.schemas.stats import AnovaRequest, EnrichmentRequest
from app.services import stats_tools
from app.services.stats_tools import _anova_cluster_dataframe

METHODS = ("average", "ward", "complete", "weighted", "single")


def _frame(n=160, seed=5):
    """Three condition blocks with distinct profiles, so clusters are real."""
    rng = np.random.default_rng(seed)
    samples = [f"{c}_{i}" for c in ("A", "B", "C") for i in range(1, 5)]
    base = rng.normal(20, 0.35, (n, len(samples)))
    base[: n // 3, 0:4] += 2.5
    base[n // 3 : 2 * n // 3, 4:8] += 2.5
    frame = pd.DataFrame(base, columns=samples)
    frame.insert(0, "ProteinNames", [f"P{i:04d}" for i in range(n)])
    frame["adj_pval"] = rng.uniform(0, 0.01, n)
    metadata = pd.DataFrame(
        {"sample": samples, "condition": [c for c in ("A", "B", "C") for _ in range(4)]}
    )
    return frame, metadata


def _clusters(method, n_clusters=3):
    frame, metadata = _frame()
    payload = AnovaRequest(
        kind="protein", source="anova_cluster", nClusters=n_clusters,
        clusterMethod=method,
    )
    out, _ = _anova_cluster_dataframe(frame, metadata, payload)
    return out.set_index("ProteinNames")["cluster"]


def test_the_default_is_unchanged() -> None:
    """Existing figures must reproduce; average is what clustering always used."""
    assert AnovaRequest(kind="protein").clusterMethod == "average"
    assert EnrichmentRequest(kind="protein").clusterMethod == "average"


@pytest.mark.parametrize("method", METHODS)
def test_every_offered_method_runs(method: str) -> None:
    assigned = _clusters(method)
    assert len(assigned) == 160
    assert set(assigned.unique()) <= {1, 2, 3}


@pytest.mark.parametrize("method", METHODS)
def test_every_offered_method_is_accepted_by_the_schema(method: str) -> None:
    assert AnovaRequest(kind="protein", clusterMethod=method).clusterMethod == method


def test_an_unknown_method_is_rejected_before_it_reaches_scipy() -> None:
    with pytest.raises(Exception):
        AnovaRequest(kind="protein", clusterMethod="not-a-linkage")


def test_the_method_actually_changes_the_partition() -> None:
    """Otherwise the control is decorative."""
    average = _clusters("average")
    ward = _clusters("ward")
    assert not average.equals(ward), "average and ward produced the same partition"


def test_clusters_are_numbered_in_dendrogram_order_for_every_method() -> None:
    """Cluster 1 is the top block of the heatmap, whichever linkage ran."""
    for method in METHODS:
        assigned = _clusters(method).tolist()
        first_seen = []
        for value in assigned:
            if value not in first_seen:
                first_seen.append(value)
        assert first_seen == sorted(first_seen), (
            f"{method}: cluster numbers do not ascend in row order: {first_seen}"
        )


def test_ora_resolves_a_cluster_with_the_method_it_was_given(monkeypatch) -> None:
    """ORA rebuilds the ANOVA; the rebuild must carry the caller's linkage.

    Without it, ORA silently enriches whatever cluster 2 happens to be under the
    default linkage, which need not be the cluster 2 the user selected.
    """
    seen: list[str] = []
    real = stats_tools._anova_cluster_dataframe

    def spy(anova_df, metadata, payload):
        seen.append(payload.clusterMethod)
        return real(anova_df, metadata, payload)

    frame, metadata = _frame()
    monkeypatch.setattr(stats_tools, "_anova_cluster_dataframe", spy)
    monkeypatch.setattr(
        stats_tools, "_anova_dataframe",
        lambda payload: ("filtered", "ProteinNames", frame.copy(), []),
    )
    monkeypatch.setattr(
        stats_tools, "_stats_source",
        lambda kind, data_source=None: ("filtered", frame.copy(), metadata.copy(), []),
    )

    stats_tools._anova_cluster_genes(
        EnrichmentRequest(
            kind="protein", source="anova", selectedCluster=1,
            nClusters=3, clusterMethod="ward",
        )
    )
    assert seen == ["ward"], f"ORA clustered with {seen}, not the requested ward"
