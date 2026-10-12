"""Dimensionality-reduction code and frozen coordinates for exact visual replay."""
from functools import lru_cache
import inspect
import json
import sys
from types import ModuleType

from app.services.notebook_archive import NotebookRecipe, dataframe_bytes
from app.services.notebook_preprocessing import capture_notebook
from app.services.notebook_qc import qc_source
from app.services.notebook_source import extract_notebook_source, function_definition, merge_source, module_source, replace_once
from app.services.notebook_provenance import input_history

PROJECTION_OPTIONS = ("data_source", "plot_dim", "method", "umap_n_neighbors", "umap_min_dist",
                      "tsne_perplexity", "tsne_learning_rate", "random_state", "scaling")
CLUSTER_OPTIONS = ("cluster_method", "cluster_count", "dbscan_eps_factor", "dbscan_min_samples", "random_state")
METHODS = {"pca": ("PCA", "PC"), "umap": ("UMAP", "UMAP"), "t-sne": ("t-SNE", "t-SNE")}


def _method_key(method):
    key = str(method).strip().lower()
    key = "t-sne" if key in {"tsne", "t_sne"} else key
    if key not in METHODS:
        raise ValueError("Unsupported dimensionality-reduction method. Use PCA, UMAP, or t-SNE.")
    return key


@lru_cache(maxsize=6)
def pca_source(interactive=False, method="pca"):
    method = _method_key(method)
    name, prefix = METHODS[method]
    rendering = module_source("plot_images.py")
    projection = function_definition(rendering, "_pca_projection")
    for before, after in (
        ("def _pca_projection(", "def project("),
        ("    kind: AnnotationKind,", "    data, metadata,"),
        ("_, frame, _ = select_matrix(kind, data_source)", "frame = data"),
        ("_get_sample_columns(kind, frame)", "metadata['sample'].tolist()"),
        ("_metadata_for_kind(kind, frame, sample_columns).copy()", "metadata.copy()"),
    ):
        projection = replace_once(projection, before, after)
    # Include only the selected algorithm, not the other methods' dependencies.
    start = projection.index('    if method_key == "pca":')
    umap = projection.index('    elif method_key == "umap":', start)
    tsne = projection.index('    elif method_key in {"t-sne", "tsne", "t_sne"}:', umap)
    end = projection.index('    else:\n        raise ValueError("Unsupported dimensionality', tsne)
    branches = {"pca": projection[start:umap], "umap": projection[umap:tsne], "t-sne": projection[tsne:end]}
    selected = branches[method].replace("    elif ", "    if ", 1)
    projection = projection[:start] + selected + projection[end:]
    projection = projection.replace("Use PCA, UMAP, or t-SNE.", f"This notebook exports {name} only.")
    projection = projection.replace('method: str = "PCA"', f'method: str = "{name}"')
    renderer = "qc_pca_interactive_html" if interactive else "qc_pca_plot"
    figure = function_definition(rendering, renderer)
    figure = replace_once(figure, f"def {renderer}(", "def plot_figure(")
    figure = replace_once(figure, "    kind: AnnotationKind,", "    scores, explained, cluster_labels, condition_colors,")
    begin = figure.index("    pca_scores, explained, axis_prefix = _pca_projection(")
    end = figure.index("    plot_3d =" if interactive else "    n_components =", begin)
    figure = figure[:begin] + f'    pca_scores = scores.copy()\n    axis_prefix = "{prefix}"\n' + figure[end:]
    begin = figure.index("    cluster_labels = _compute_cluster_labels(")
    end = figure.index("    if cluster_labels is not None:", begin)
    figure = figure[:begin] + figure[end:]
    palette = "None" if interactive else "plt"
    figure = replace_once(figure, f"advanced_condition_colors(kind, {palette}, groups, advanced)", "condition_colors")
    if interactive:
        assert figure.count("return _plotly_html(fig)") == 2
        figure = figure.replace("return _plotly_html(fig)", "return force_svg_rendering(fig)")
        figure = figure.replace("_get_plotly()", "get_plotly()").replace("_cm_to_px(", "cm_to_px(")
    else:
        figure = replace_once(figure, "return _to_png_bytes(fig, plt, dpi=dpi)", "return fig")
    figure = figure.replace("_get_plt()", "get_plt()").replace("_cm_to_inch(", "cm_to_inch(")
    shared = extract_notebook_source(qc_source("coverage").code, (
        "get_plt", "to_png_bytes", "cm_to_inch", "_make_fig", "advanced_anchor", "advanced_label",
        "marker_style", "apply_advanced_axes")).code
    styles = extract_notebook_source(module_source("plot_styling.py"), ("pca_default_size",)).code
    if interactive:
        from app.services.notebook_interactive import abundance_source
        shared = extract_notebook_source(abundance_source().code, (
            "get_plotly", "plotly_html", "cm_to_px", "force_svg_rendering", "advanced_label",
            "advanced_element_text", "apply_plotly_group_markers", "advanced_plotly_layout")).code
    helpers = extract_notebook_source(rendering, ("_pca_feature_matrix", "_compute_cluster_labels", "_cluster_display_label", "fitted_group_ellipse")).code
    scaling = extract_notebook_source(module_source("functions.py"), ("resolve_feature_scaling",)).code
    source = merge_source(shared, styles, helpers, scaling, projection, figure)
    serializers = ("plotly_html",) if interactive else ("to_png_bytes", "get_plt")
    return extract_notebook_source(source, ("plot_figure", "project", "_compute_cluster_labels", *serializers))


@lru_cache(maxsize=6)
def _pca_module(interactive=False, method="pca"):
    module = ModuleType(f"_copylot_portable_projection_{method}_{interactive}")
    sys.modules[module.__name__] = module
    exec(pca_source(interactive, method).code, module.__dict__)
    return module




def render_pca(kind: str, *, interactive=False, **options) -> tuple[bytes | str, str]:
    from app.services.annotation_store import get_annotation
    from app.services.dataset_store import get_current_dataset
    from app.services.data_tools import metadata_for_kind, _get_sample_columns
    from app.services.analysis_matrix import select_matrix
    from app.services.plot_images import qc_pca_plot, qc_pca_interactive_html
    from app.services.plot_styling import advanced_condition_colors
    from app.services.plot_export import plot_output_format
    from app.services.runtime_cache import runtime_cache_version
    from app.services.session_context import get_session_id

    if kind not in {"protein", "phospho", "phosprot"}:
        raise ValueError("This notebook adapter supports protein, phosphosite and phosphoprotein projections only.")
    method = _method_key(options.get("method", "PCA"))
    name, _ = METHODS[method]
    revision = runtime_cache_version()
    annotation, dataset = get_annotation(kind), get_current_dataset(kind)
    if annotation is None or dataset is None:
        raise ValueError("Load and annotate a dataset first.")
    source, data, _ = select_matrix(kind, options.get("data_source", "data"))
    metadata = metadata_for_kind(kind, data, _get_sample_columns(kind, data)).copy(deep=True)
    lineage, imputation, uses_imputed_input, imputation_text = input_history(kind, annotation, dataset, source)
    bound = inspect.signature(qc_pca_interactive_html if interactive else qc_pca_plot).bind(kind, **options)
    bound.apply_defaults()
    settings = dict(bound.arguments)
    settings.pop("kind")
    module = _pca_module(interactive, method)
    scores, explained, prefix = module.project(data, metadata, **{key: settings[key] for key in PROJECTION_OPTIONS})
    components = [f"{prefix}{i + 1}" for i in range(3 if settings["plot_dim"] == "3D" else 2)]
    labels = module._compute_cluster_labels(scores[components].to_numpy(dtype=float), **{key: settings[key] for key in CLUSTER_OPTIONS})
    if str(settings["color_by"]).lower() == "cluster" and labels is not None:
        groups = list(dict.fromkeys(module._cluster_display_label(value) for value in labels))
    else:
        groups = scores["condition"].astype(str).dropna().unique().tolist()
    settings["condition_colors"] = advanced_condition_colors(kind, None if interactive else module.get_plt(), groups, settings["advanced"])
    figure = module.plot_figure(scores, explained, labels, **settings)
    fmt = "html" if interactive else plot_output_format.get()
    if interactive:
        content = module.plotly_html(figure)
    else:
        format_token = module.plot_output_format.set(fmt)
        try:
            content = module.to_png_bytes(figure, module.get_plt(), dpi=settings["dpi"])
        finally:
            module.plot_output_format.reset(format_token)
    output_resources = {"original.html": content.encode(), "figure.json": figure.to_json().encode()} if interactive else {f"original.{fmt}": bytes(content)}
    replay_output = (
        "assert json.loads(figure.to_json()) == json.loads((RESOURCES / 'figure.json').read_text())\n"
        "Path('reproduced.html').write_text(functions.plotly_html(figure), encoding='utf-8', newline='')\n"
        "display(IFrame('reproduced.html', width='100%', height=600))" if interactive else
        "image = functions.to_png_bytes(figure, functions.get_plt(), dpi=settings['dpi'])\n"
        "Path('reproduced.png').write_bytes(image)\ndisplay(Image(data=image))")
    projection = {"axisPrefix": prefix, "explained": None if explained is None else explained.tolist(),
                  "clusterLabels": None if labels is None else labels.tolist()}
    complete = data[metadata["sample"].tolist()].apply(module.pd.to_numeric, errors="coerce").replace(
        [module.np.inf, -module.np.inf], module.np.nan).dropna()
    recipe = NotebookRecipe(
        plot_name=f"{'Interactive ' if interactive else ''}{name} {settings['plot_dim']}", source=pca_source(interactive, method), settings=settings, original_filename=dataset.filename,
        provenance={"kind": kind, "plot": "pca", "method": name, "view": "interactive" if interactive else "static", "dataSource": source,
            "inputScale": "site-centered log2 ratios" if lineage and lineage.aggregation == "robust_site_median" else "log2",
            "upstreamCollapse": lineage.model_dump() if lineage else None,
            "filter": annotation.filter_config.model_dump(), "filterAppliedToThisPlot": source != "data",
            "imputation": imputation.model_dump() if imputation else None,
            "normalization": annotation.filter_config.normalization,
            "normalizationScope": "after_collapse" if lineage else "within_this_annotation",
            "resolvedScaling": module.resolve_feature_scaling(settings["scaling"], method=name),
            "featureCounts": {"total": len(data), "complete": len(complete), "used": int((complete.T.var(axis=0) > 0).sum())},
            "projectionReplay": "Frozen coordinates, explained variance where applicable and cluster labels preserve orientation, stochastic embedding and grouping"},
        resources={"input.parquet": dataframe_bytes(data), "metadata.parquet": dataframe_bytes(metadata),
            "scores.parquet": dataframe_bytes(scores), "projection.json": json.dumps(projection, allow_nan=False).encode(),
            **output_resources},
        uses_imputed_input=uses_imputed_input, imputation_recipe=imputation_text,
        calculation="from IPython.display import Image, IFrame, display\n"
            "# The original calculation code is included for inspection/recalculation:\n"
            f"# projection_options = {{key: settings[key] for key in {PROJECTION_OPTIONS!r}}}\n"
            "# scores, explained, prefix = functions.project(data, metadata, **projection_options)\n"
            f"# cluster_options = {{key: settings[key] for key in {CLUSTER_OPTIONS!r}}}\n"
            "# components = [f'{prefix}{i + 1}' for i in range(3 if settings['plot_dim'] == '3D' else 2)]\n"
            "# labels = functions._compute_cluster_labels(scores[components].to_numpy(dtype=float), **cluster_options)\n"
            "# Replay captured coordinates: SVD signs, stochastic embeddings and clustering can vary across platforms.\n"
            "scores = pd.read_parquet(RESOURCES / 'scores.parquet')\n"
            "projection = json.loads((RESOURCES / 'projection.json').read_text())\n"
            "figure = functions.plot_figure(scores, projection['explained'], projection['clusterLabels'], **settings)\n"
            + replay_output,
        input_explanation=f"The exact selected analysis matrix and {name} coordinates are included. "
            "Complete, non-constant features and the selected scaling are used by the supplied calculation code. "
            "Replay uses captured coordinates and cluster labels to preserve the displayed orientation. "
            "Original-file normalization/filtering replay is not yet included."
            + (" Phosphosite collapse is documented in upstreamCollapse and is not rerun; the exact resulting matrix is imported." if lineage else ""),
    )
    try:
        token = capture_notebook(get_session_id(), recipe) if runtime_cache_version() == revision else ""
    except ValueError:
        token = ""
    return content, token
