"""Completeness replay from the same observed input used by the app."""
from functools import lru_cache
import inspect
import sys
from types import ModuleType

from app.services.notebook_archive import NotebookRecipe, dataframe_bytes
from app.services.notebook_preprocessing import capture_notebook
from app.services.notebook_snapshots import snapshots
from app.services.notebook_source import extract_notebook_source, function_definition, merge_source, module_source, replace_once

RENDERERS = {"missing-value": "completeness_missing_value_plot",
             "missing-heatmap": "completeness_missing_value_heatmap"}


@lru_cache(maxsize=2)
def completeness_source(plot):
    if plot not in RENDERERS:
        raise ValueError("Unsupported completeness notebook plot.")
    original = module_source("completeness_tools.py")
    names = ("_feature_label", "_renamed_meta", "_selected_matrix", "_filtered_data",
             "completeness_sample_summary_table", "completeness_feature_summary_table", RENDERERS[plot])
    code = "\n\n".join(function_definition(original, name) for name in names)
    code = code.replace("kind: AnnotationKind,", "frame: pd.DataFrame, meta: pd.DataFrame,")
    code = code.replace("    frame, meta = _frame_and_meta(kind)\n", "")
    code = code.replace("_extract_id_or_number", "extract_sample_id")
    code = replace_once(code, f"def {RENDERERS[plot]}(", "def plot_figure(")
    if plot == "missing-value":
        code += "\n\n" + function_definition(original, "_missing_value_plot_from_matrix")
    code = code.replace("return _to_png_bytes(fig, plt, dpi=dpi, tight=True)", "return fig")
    code = code.replace("return _to_png_bytes(fig, plt, dpi=dpi)", "return fig")
    code = code.replace("_get_plt()", "get_plt()").replace("_get_sns()", "get_sns()")
    code = code.replace("_cm_to_inch(", "cm_to_inch(")
    styling = "\n".join(line for line in module_source("plot_styling.py").splitlines()
                        if not line.startswith("from app."))
    styling += "\n\n" + function_definition(module_source("plotting_common.py"), "get_plt")
    styling += "\n\ndef _get_plt():\n    return get_plt()\n"
    styles = extract_notebook_source(styling, (
        "advanced_label", "advanced_color", "advanced_label_size", "apply_advanced_axes", "get_plt")).code
    notebook = extract_notebook_source(module_source("notebook_functions.py"), ("extract_sample_id",)).code
    serialization = extract_notebook_source(module_source("plot_export.py"), ("to_png_bytes", "cm_to_inch")).code
    combined = merge_source("import pandas as pd", styles, notebook, serialization, code,
                             function_definition(module_source("plotting_common.py"), "get_sns"))
    return extract_notebook_source(combined, ("plot_figure", "to_png_bytes", "get_plt",
        "completeness_sample_summary_table", "completeness_feature_summary_table", "_selected_matrix"))


@lru_cache(maxsize=2)
def _completeness_module(plot):
    module = ModuleType(f"_copylot_portable_completeness_{plot.replace('-', '_')}")
    sys.modules[module.__name__] = module
    exec(completeness_source(plot).code, module.__dict__)
    return module


def render_completeness(kind, *, plot, table_include_id=True, outlier_threshold=50.0, **options):
    from app.services import completeness_tools
    from app.services.annotation_store import get_annotation
    from app.services.dataset_store import get_current_dataset
    from app.services.notebook_provenance import input_history, NotebookProvenanceError
    from app.services.plot_export import plot_output_format
    from app.services.runtime_cache import runtime_cache_version
    from app.services.session_context import get_session_id

    revision = runtime_cache_version()
    annotation, dataset = get_annotation(kind), get_current_dataset(kind)
    if annotation is None:
        raise NotebookProvenanceError("Annotate the dataset before exporting its scientific history.")
    lineage, imputation, uses_imputed_input, imputation_text = input_history(kind, annotation, dataset)
    frame, metadata = completeness_tools._frame_and_meta(kind)
    # Completeness needs only the feature label and sample values, not arbitrary importer columns.
    feature_column = next((name for name in ("Phosphoprotein", "PTM_Collapse_key", "ProteinNames")
                           if name in frame.columns), None)
    columns = list(dict.fromkeys(([feature_column] if feature_column else []) + metadata["sample"].tolist()))
    frame = frame[columns].copy(deep=True)
    metadata = metadata[["sample", "condition"]].copy(deep=True)
    bound = inspect.signature(getattr(completeness_tools, RENDERERS[plot])).bind(kind, **options)
    bound.apply_defaults()
    plot_settings = dict(bound.arguments)
    plot_settings.pop("kind")
    settings = {"plot": plot_settings, "table_include_id": table_include_id,
                "outlier_threshold": outlier_threshold}
    module = _completeness_module(plot)
    figure = module.plot_figure(frame, metadata, **plot_settings)
    fmt = plot_output_format.get()
    format_token = module.plot_output_format.set(fmt)
    try:
        content = module.to_png_bytes(figure, module.get_plt(), dpi=plot_settings["dpi"])
    finally:
        module.plot_output_format.reset(format_token)
    resources = {"input.parquet": dataframe_bytes(frame), "metadata.parquet": dataframe_bytes(metadata),
                 f"original.{fmt}": bytes(content)}
    for name in ("sample", "feature"):
        table = getattr(module, f"completeness_{name}_summary_table")(frame, metadata, include_id=table_include_id)
        resources[f"{name}_summary.parquet"] = dataframe_bytes(table)
    matrix, _, excluded = module._selected_matrix(frame, metadata, include_id=table_include_id)
    recipe = NotebookRecipe(
        plot_name="Missing Value Plot" if plot == "missing-value" else "Missing Value Heatmap",
        source=completeness_source(plot), settings=settings, original_filename=dataset.filename,
        resources=resources, uses_imputed_input=uses_imputed_input, imputation_recipe=imputation_text,
        provenance={"kind": kind, "plot": f"completeness/{plot}",
            "dataSource": "source_data", "excludedAllMissingCount": excluded,
            "overallMissingPercent": round(int(matrix.isna().sum().sum()) / max(1, int(matrix.size)) * 100, 2),
            "zeroIsMissing": not annotation.is_log2_transformed,
            "normalizationAppliedToThisPlot": False, "filterAppliedToThisPlot": False,
            "imputationAppliedToThisPlot": uses_imputed_input,
            "upstreamCollapse": lineage.model_dump() if lineage else None,
            "imputation": imputation.model_dump() if imputation else None},
        input_explanation="This is the exact observed source matrix used by completeness, before this level's "
            "normalization, filtering and imputation. Linear zero/non-finite handling has already been applied "
            "where required by the original renderer. The notebook repeats sample labelling and exclusion of "
            "features missing in every selected sample, and reproduces the plot and summary tables. "
            "For phosphoproteins, the captured source is the collapsed matrix; its upstream processing is "
            "recorded separately and is not rerun. Original-upload preprocessing replay is not yet included.",
        calculation="from IPython.display import Image, display\n"
            "sample_summary = functions.completeness_sample_summary_table(data, metadata, include_id=settings['table_include_id'])\n"
            "feature_summary = functions.completeness_feature_summary_table(data, metadata, include_id=settings['table_include_id'])\n"
            "for name, table in [('sample', sample_summary), ('feature', feature_summary)]:\n"
            "    pd.testing.assert_frame_equal(table, pd.read_parquet(RESOURCES / f'{name}_summary.parquet'), check_exact=True)\n"
            "    table.to_csv(f'reproduced_{name}_summary.csv', index=False)\n"
            "    display(table)\n"
            "outliers = sample_summary.loc[sample_summary['%_missing_values'] > settings['outlier_threshold'], ['Sample']]\n"
            "outliers.to_csv('reproduced_outliers.csv', index=False)\ndisplay(outliers)\n"
            "figure = functions.plot_figure(data, metadata, **settings['plot'])\n"
            "image = functions.to_png_bytes(figure, functions.get_plt(), dpi=settings['plot']['dpi'])\n"
            "Path('reproduced.png').write_bytes(image)\ndisplay(Image(data=image))",
    )
    try:
        token = capture_notebook(get_session_id(), recipe) if runtime_cache_version() == revision else ""
    except ValueError:
        token = ""
    return content, token


def snapshot_tables(kind, snapshot, *, include_id, outlier_threshold):
    import io
    import pandas as pd
    from fastapi import HTTPException
    from app.schemas.completeness import CompletenessTablesResponse
    from app.services.session_context import get_session_id

    try:
        recipe = snapshots.peek(get_session_id(), snapshot)
    except KeyError as exc:
        raise HTTPException(404, "Notebook snapshot unavailable; refresh the completeness output.") from exc
    if (recipe.provenance.get("kind") != kind
            or recipe.provenance.get("plot") not in {f"completeness/{plot}" for plot in RENDERERS}
            or recipe.settings.get("table_include_id") != include_id
            or recipe.settings.get("outlier_threshold") != outlier_threshold):
        raise HTTPException(409, "The table settings do not match the captured completeness plot.")
    sample = pd.read_parquet(io.BytesIO(recipe.resources["sample_summary.parquet"]))
    feature = pd.read_parquet(io.BytesIO(recipe.resources["feature_summary.parquet"]))
    return CompletenessTablesResponse(
        kind=kind, overallMissingPercent=recipe.provenance["overallMissingPercent"],
        excludedAllMissingCount=recipe.provenance["excludedAllMissingCount"],
        outlierThreshold=outlier_threshold,
        outliers=sample.loc[sample["%_missing_values"] > outlier_threshold, "Sample"].astype(str).tolist(),
        sampleSummary=sample.to_dict(orient="records"), featureSummary=feature.to_dict(orient="records"))


@lru_cache(maxsize=1)
def peptide_source():
    return extract_notebook_source(completeness_source("missing-value").code,
                                  ("_missing_value_plot_from_matrix", "to_png_bytes", "get_plt"))


@lru_cache(maxsize=1)
def _peptide_module():
    module = ModuleType("_copylot_portable_peptide_missing_values")
    sys.modules[module.__name__] = module
    exec(peptide_source().code, module.__dict__)
    return module


def render_peptide_missing_values(level, **options):
    import pandas as pd
    from app.services import completeness_tools
    from app.services.dataset_store import get_current_dataset
    from app.services.notebook_archive import portable_filename
    from app.services.plot_export import plot_output_format
    from app.services.runtime_cache import runtime_cache_version
    from app.services.session_context import get_session_id

    if level not in {"peptide", "precursor"}:
        raise ValueError("Choose peptide or precursor completeness.")
    revision = runtime_cache_version()
    dataset = get_current_dataset("peptide")
    if dataset is None:
        raise ValueError("Load a peptide dataset first.")
    renderer = getattr(completeness_tools, f"completeness_missing_value_plot_{level}")
    bound = inspect.signature(renderer).bind(**options)
    bound.apply_defaults()
    settings = dict(bound.arguments)
    matrix = completeness_tools.completeness_peptide_matrix(level, settings.pop("quantity_column"))
    # Missing-count bars do not use run names. Keep basenames, disambiguated without exposing paths.
    labels = []
    for column in matrix.columns:
        base = portable_filename(str(column)) or "sample"
        label = base
        suffix = 2
        while label in labels:
            label = f"{base} ({suffix})"
            suffix += 1
        labels.append(label)
    matrix.columns = labels
    metadata = pd.DataFrame({"sample": labels})
    settings["title_label"] = level.capitalize()
    module = _peptide_module()
    figure = module._missing_value_plot_from_matrix(matrix, **settings)
    fmt = plot_output_format.get()
    format_token = module.plot_output_format.set(fmt)
    try:
        content = module.to_png_bytes(figure, module.get_plt(), dpi=settings["dpi"])
    finally:
        module.plot_output_format.reset(format_token)
    recipe = NotebookRecipe(
        plot_name=f"{level.capitalize()} Missing Values", source=peptide_source(), settings=settings,
        original_filename=dataset.filename,
        resources={"input.parquet": dataframe_bytes(matrix), "metadata.parquet": dataframe_bytes(metadata),
                   f"original.{fmt}": bytes(content)},
        provenance={"kind": level, "plot": "completeness/missing-value", "inputScale": "linear",
            "featureColumn": matrix.attrs["feature_column"], "quantityColumn": matrix.attrs["quantity_column"],
            "aggregation": "maximum quantity per feature/run", "zeroIsMissing": True,
            "excludedAllMissingCount": int(matrix.isna().all(axis=1).sum()),
            "normalizationAppliedToThisPlot": False, "filterAppliedToThisPlot": False,
            "imputationAppliedToThisPlot": False},
        input_explanation="The captured selected-quantity matrix uses the app's metadata-selected runs and "
            "maximum quantity per feature/run. Peptides use stripped sequence; precursors use the precursor ID. "
            "Linear zero and non-finite quantities are already missing. The notebook excludes all-missing "
            "features before bucketing their missing counts, exactly as the app does. Run paths are replaced "
            "by unique basenames; this does not affect counts. Original-upload preprocessing is not rerun.",
        calculation="from IPython.display import Image, display\n"
            "figure = functions._missing_value_plot_from_matrix(data, **settings)\n"
            "image = functions.to_png_bytes(figure, functions.get_plt(), dpi=settings['dpi'])\n"
            "Path('reproduced.png').write_bytes(image)\ndisplay(Image(data=image))",
    )
    try:
        token = capture_notebook(get_session_id(), recipe) if runtime_cache_version() == revision else ""
    except ValueError:
        token = ""
    return content, token
