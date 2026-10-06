"""UMAP and t-SNE settings that exceed what the sample count supports are named.

UMAP with n_neighbors at or above the number of samples treats every sample as
a neighbour of every other, and t-SNE's perplexity has to be lowered below the
sample count. The QC page shows a notice beside the plot; PCA gets none.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


def _notice(**params):
    with TestClient(app) as client:
        response = client.get("/api/plots/qc/protein/pca-features", params=params)
    assert response.status_code == 200, response.text[:300]
    return response.json()["smallSampleNotice"]


def test_umap_neighbours_at_or_above_the_sample_count(qc_protein_data):
    notice = _notice(method="UMAP", umapNNeighbors=15)
    assert notice.startswith("UMAP n_neighbors is 15 but there are only 6 samples")
    assert "at most 5" in notice
    assert _notice(method="UMAP", umapNNeighbors=6).startswith("UMAP n_neighbors is 6")
    assert _notice(method="UMAP", umapNNeighbors=5) is None


def test_tsne_perplexity_lowered_for_few_samples(qc_protein_data):
    assert _notice(method="t-SNE", tsnePerplexity=30).startswith(
        "t-SNE perplexity 30 was lowered to 5 because there are only 6 samples.")
    assert _notice(method="t-SNE", tsnePerplexity=5) is None


@pytest.mark.parametrize("params", [{"method": "PCA"}, {"method": "PCA", "umapNNeighbors": 50}])
def test_pca_gets_no_notice(qc_protein_data, params):
    assert _notice(**params) is None
