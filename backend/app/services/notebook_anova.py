"""Portable ANOVA calculations and heatmaps extracted from the application."""
from functools import lru_cache
import json
import sys
from types import ModuleType

from app.services.notebook_archive import NotebookRecipe, dataframe_bytes
from app.services.notebook_preprocessing import capture_notebook
from app.services.notebook_source import extract_notebook_source, function_definition, merge_source, module_source, replace_once
from app.services.notebook_volcano import volcano_source


@lru_cache(maxsize=1)
def anova_source():
    original = module_source("stats_tools.py")
    calculation = function_definition(original, "_anova_dataframe")
    calculation = replace_once(calculation, "    payload: AnovaRequest,",
                                "    payload: SimpleNamespace, data, metadata, imputation_mask=None,")
    calculation = replace_once(calculation,
        "    source_used, frame, metadata, warnings = _stats_source(payload.kind, data_source=payload.dataSource)",
        "    source_used, frame, warnings = payload.dataSource, data.copy(), []")
    calculation = replace_once(calculation,
        "mask = _imputation_mask(payload.kind, source_used, frame.loc[df.index], sample_cols)",
        "mask = imputation_mask")
    tables = function_definition(original, "run_anova")
    tables = replace_once(tables, "def run_anova(payload: AnovaRequest) -> AnovaResultResponse:",
        "def calculate_tables(data, metadata, request, imputation_mask=None):\n    payload = SimpleNamespace(**request)")
    tables = replace_once(tables, "_anova_dataframe(payload)",
                           "_anova_dataframe(payload, data, metadata, imputation_mask)")
    start = tables.index("    metadata: pd.DataFrame | None = None")
    end = tables.index("    completeness_notice:", start)
    tables = tables[:start] + tables[end:]
    tables = replace_once(tables, "return AnovaResultResponse(", "return dict(")
    prepare = function_definition(original, "_prepare_anova_plot_frame")
    prepare = replace_once(prepare, "    payload: AnovaRequest,",
                            "    data, metadata, request, imputation_mask=None,")
    prepare = replace_once(prepare,
        "    _, label_column, anova_df, _ = _anova_dataframe(payload)\n    _, _, metadata, _ = _stats_source(payload.kind, data_source=payload.dataSource)",
        "    payload = SimpleNamespace(**request)\n    _, label_column, anova_df, _ = _anova_dataframe(payload, data, metadata, imputation_mask)")
    figure = function_definition(original, "_anova_heatmap_figure")
    figure = replace_once(figure, "    kind: AnnotationKind,", "    condition_palette: dict,")
    figure = replace_once(figure,
        "condition_hex = advanced_condition_colors(kind, plt, unique_conditions, advanced)",
        "condition_hex = condition_palette")
    rendering = function_definition(original, "anova_png")
    rendering = replace_once(rendering,
        "def anova_png(payload: AnovaRequest, selected_cluster: int | None = None, advanced: dict | None = None) -> bytes:",
        "def render_plot(data, metadata, request, condition_palette, imputation_mask=None, selected_cluster=None, advanced=None):\n    payload = SimpleNamespace(**request)")
    rendering = replace_once(rendering,
        "_prepare_anova_plot_frame(payload, selected_cluster=selected_cluster)",
        "_prepare_anova_plot_frame(data, metadata, request, imputation_mask, selected_cluster=selected_cluster)")
    rendering = replace_once(rendering, "kind=payload.kind,", "condition_palette=condition_palette,")
    helpers = "\n\n".join(function_definition(original, name) for name in (
        "_anova_cluster_dataframe", "_condition_columns"))
    styles = "\n".join(line for line in module_source("plot_styling.py").splitlines()
                       if not line.startswith("from app."))
    code = merge_source(
        "import numpy as np\nimport pandas as pd\nfrom types import SimpleNamespace\n"
        "from scipy.cluster.hierarchy import linkage, leaves_list, fcluster",
        extract_notebook_source(volcano_source().code, (
            "_resolve_label_column", "_correction_label", "_safe_neg_log10", "_bh_adjust",
            "imputed_value_counts", "constant_within_group", "get_plt", "to_png_bytes",
            "apply_advanced_axes")).code,
        extract_notebook_source(styles, ("advanced_element_number", "advanced_color_text", "advanced_label")).code,
        extract_notebook_source(module_source("clustering_tools.py"), (
            "CompletenessReport", "drop_incomplete_features", "row_zscore", "heatmap_notice", "completeness_message")).code,
        extract_notebook_source(module_source("functions.py"), ("anova_posthoc_data", "entity_labels_for_kind")).code,
        calculation, tables, prepare, helpers, figure, rendering)
    for before, after in (("AnovaRequest", "SimpleNamespace"), ("ResolvedSource", "str"),
                          ("_get_plt()", "get_plt()"), ("_to_png_bytes(", "to_png_bytes(")):
        code = code.replace(before, after)
    return extract_notebook_source(code, ("calculate_tables", "render_plot"))


@lru_cache(maxsize=1)
def anova_module():
    module = ModuleType("_copylot_portable_anova")
    sys.modules[module.__name__] = module
    exec(anova_source().code, module.__dict__)
    return module


def render_anova(payload, *, selected_cluster=None, advanced=None):
    from app.services import stats_tools
    from app.services.annotation_store import get_annotation
    from app.services.dataset_store import get_current_dataset
    from app.services.notebook_provenance import input_history
    from app.services.plot_export import plot_output_format
    from app.services.plot_styling import advanced_condition_colors
    from app.services.runtime_cache import runtime_cache_version
    from app.services.session_context import get_session_id
    import pandas as pd

    revision = runtime_cache_version()
    kind = payload.kind
    source, data, metadata, warnings = stats_tools._stats_source(kind, data_source=payload.dataSource)
    annotation, dataset = get_annotation(kind), get_current_dataset(kind)
    lineage, imputation, uses_imputed, imputation_text = input_history(kind, annotation, dataset, source=source)
    metadata = metadata[[c for c in ("sample", "condition", "new_sample") if c in metadata]].copy(deep=True)
    mask = stats_tools._imputation_mask(kind, source, data, metadata["sample"].astype(str).tolist())
    identifiers = ["GeneNames", "Gene_group", "ProteinNames", "PTM_Collapse_key", "Phosphoprotein",
                   "site_num", "PTM_Collapse_keys", "Protein_group"]
    columns = list(dict.fromkeys(metadata["sample"].astype(str).tolist() + identifiers))
    data = data[[c for c in columns if c in data]].copy(deep=True)
    request = payload.model_dump()
    request["dataSource"] = source
    module = anova_module()
    palette = advanced_condition_colors(kind, module.get_plt(),
        metadata["condition"].astype(str).drop_duplicates().tolist(), advanced)
    results = module.calculate_tables(data, metadata, request, mask)
    figure_settings = dict(selected_cluster=selected_cluster, advanced=advanced, condition_palette=palette)
    fmt = plot_output_format.get()
    format_token = module.plot_output_format.set(fmt)
    try:
        content = module.render_plot(data, metadata, request, imputation_mask=mask, **figure_settings)
    finally:
        module.plot_output_format.reset(format_token)
    resources = {"input.parquet": dataframe_bytes(data), "metadata.parquet": dataframe_bytes(metadata),
                 f"original.{fmt}": bytes(content)}
    for key in ("rows", "clusterRows", "postHocRows"):
        resources[f"{key}.parquet"] = dataframe_bytes(pd.DataFrame(results[key]))
    summary = {key: value for key, value in results.items() if key not in {"rows", "clusterRows", "postHocRows"}}
    summary["warnings"] = [*warnings, *results["warnings"]]
    resources["summary.json"] = json.dumps(summary, allow_nan=False).encode("utf-8")
    if mask is not None:
        resources["imputation_mask.parquet"] = dataframe_bytes(mask)
    recipe = NotebookRecipe(
        plot_name="ANOVA" + (f" Cluster {selected_cluster}" if selected_cluster is not None
                            else " Cluster" if payload.source == "anova_cluster" else "") + " Heatmap",
        source=anova_source(), settings={"request": request, "figure": figure_settings},
        original_filename=dataset.filename, resources=resources,
        uses_imputed_input=uses_imputed, imputation_recipe=imputation_text,
        provenance={"kind": kind, "plot": "anova", "sourceUsed": source, "request": payload.model_dump(),
            "selectedCluster": selected_cluster, "warnings": [*warnings, *results["warnings"]],
            "normalization": annotation.filter_config.normalization,
            "filter": annotation.filter_config.model_dump(),
            "upstreamCollapse": lineage.model_dump() if lineage else None,
            "imputation": imputation.model_dump() if imputation else None},
        input_explanation="This is the exact selected log2 analysis matrix and display metadata. "
            "The notebook recalculates ANOVA, p-value correction, significant-feature clustering and "
            "the requested Tukey comparisons, then redraws the selected heatmap with the captured palette. "
            "Normalization, filtering and any upstream collapse are already reflected in this matrix, "
            "not rerun from the original upload. Captured imputed values are never redrawn.",
        calculation="from IPython.display import display, Image\n"
            "mask_path = RESOURCES / 'imputation_mask.parquet'\n"
            "imputation_mask = pd.read_parquet(mask_path) if mask_path.exists() else None\n"
            "results = functions.calculate_tables(data, metadata, settings['request'], imputation_mask)\n"
            "for key in ('rows', 'clusterRows', 'postHocRows'):\n"
            "    table = pd.DataFrame(results[key])\n"
            "    pd.testing.assert_frame_equal(table, pd.read_parquet(RESOURCES / f'{key}.parquet'), check_exact=True)\n"
            "    if not table.empty:\n"
            "        table.to_csv(f'reproduced_{key}.csv', index=False)\n"
            "        display(table)\n"
            "selected_cluster = settings['figure']['selected_cluster']\n"
            "if selected_cluster is not None:\n"
            "    clusters = pd.DataFrame(results['clusterRows'])\n"
            "    selected = clusters.loc[clusters['cluster'] == selected_cluster]\n"
            "    selected.to_csv('reproduced_selected_cluster.csv', index=False)\n"
            "    display(selected)\n"
            "image = functions.render_plot(data, metadata, settings['request'], imputation_mask=imputation_mask, **settings['figure'])\n"
            "Path('reproduced.png').write_bytes(image)\ndisplay(Image(data=image))",
    )
    try:
        token = capture_notebook(get_session_id(), recipe) if runtime_cache_version() == revision else ""
    except ValueError:
        token = ""
    return content, token
