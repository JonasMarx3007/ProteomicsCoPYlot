"""The report's projection section is a PCA and says how it was made.

The QC page offers UMAP and t-SNE for exploration; the report does not carry
them, so a saved method other than PCA renders as PCA under the heading "PCA
Plot" with the PCA prose. And the figure's settings -- scaling, dimension,
clustering with its parameters, colouring, ellipses -- are written next to
it, the way the volcano writes its test, because none can be read off the
image.
"""

from __future__ import annotations


from app.services import report_function


def test_a_saved_umap_or_tsne_renders_as_pca():
    for method in ("UMAP", "t-SNE", "tSNE", "PCA"):
        options = report_function._pca_plot_options(
            {"method": method, "umapNNeighbors": 40, "tsnePerplexity": 5}
        )
        assert options["method"] == "PCA"
        assert "umap_n_neighbors" not in options and "tsne_perplexity" not in options


def test_parameters_line_for_a_plain_pca():
    html = report_function._pca_parameters_html(
        "protein", "data", report_function._pca_plot_options({})
    )
    assert html.startswith("<p><strong>Projection:</strong> PCA, 2D, centred features")
    assert "clustering: none" in html
    assert "coloured by condition" in html
    assert "no group ellipses" in html


def test_parameters_line_names_scaling_kmeans_and_ellipses():
    html = report_function._pca_parameters_html(
        "protein",
        "data",
        report_function._pca_plot_options(
            {"scaling": "unit_variance", "clusterMethod": "KMeans", "clusterCount": 4,
             "randomState": 7, "colorBy": "Cluster", "addEllipses": True}
        ),
    )
    assert "unit-variance features" in html
    assert "k-means with k = 4" in html
    assert "seed" not in html, "random seeds carry no scientific information and are not reported"
    assert "coloured by cluster" in html
    assert "minimum enclosing ellipse per group" in html


def test_parameters_line_resolves_the_dbscan_radius(monkeypatch):
    monkeypatch.setattr(
        report_function,
        "qc_pca_feature_summary",
        lambda kind, **kwargs: {
            "dbscan": {"epsFactor": 0.5, "medianSampleDistance": 12.4, "epsEffective": 6.2}
        },
    )
    html = report_function._pca_parameters_html(
        "protein", "imputed",
        report_function._pca_plot_options({"clusterMethod": "DBSCAN", "dbscanMinSamples": 3}),
    )
    assert "DBSCAN with eps = 0.5 × the median distance between samples in the projection (12.4), i.e. eps = 6.2, min_samples = 3" in html


def test_parameters_line_survives_a_failed_summary(monkeypatch):
    def boom(kind, **kwargs):
        raise RuntimeError("no data")

    monkeypatch.setattr(report_function, "qc_pca_feature_summary", boom)
    html = report_function._pca_parameters_html(
        "protein", "data", report_function._pca_plot_options({"clusterMethod": "DBSCAN"})
    )
    assert "DBSCAN with eps = 0.5 × the median distance between samples in the projection, min_samples = 2" in html


def test_3d_states_no_ellipse_choice():
    html = report_function._pca_parameters_html(
        "protein", "data", report_function._pca_plot_options({"plotDim": "3D", "addEllipses": True})
    )
    assert "PCA, 3D" in html and "ellipse" not in html
