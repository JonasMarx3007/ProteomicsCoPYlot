"""Volcano calculations and figures with explicit, frozen scientific inputs."""
import ast
from functools import lru_cache
import inspect
import sys
from types import ModuleType

from app.services.notebook_archive import NotebookRecipe, dataframe_bytes
from app.services.notebook_preprocessing import capture_notebook
from app.services.notebook_source import extract_notebook_source, function_definition, merge_source, module_source, replace_once
from app.services.functions import effective_test_type


@lru_cache(maxsize=2)
def volcano_source(interactive=False):
    original = module_source("stats_tools.py")
    calculation = function_definition(original, "_volcano_dataframe")
    calculation = replace_once(calculation, "def _volcano_dataframe(\n    *,", "def calculate_table(data, metadata, imputation_mask=None, *,")
    start = calculation.index("    if frame_override is None and metadata_override is None:")
    end = calculation.index("    label_column =", start)
    calculation = calculation[:start] + "    source_used = data_source\n    frame = data.copy()\n    metadata = metadata.copy()\n    warnings = []\n" + calculation[end:]
    calculation = calculation.replace("    frame_override: pd.DataFrame | None = None,\n", "")
    calculation = calculation.replace("    metadata_override: pd.DataFrame | None = None,\n", "")
    calculation = replace_once(calculation,
        "mask = _imputation_mask(kind, source_used, frame.loc[df.index], [c for cols in count_groups.values() for c in cols])",
        "mask = imputation_mask")
    helpers = "\n\n".join(function_definition(original, name) for name in (
        "_first_available_column", "_workflow_label_candidates", "_gene_label_candidates", "_resolve_label_column",
        "_variance_and_count", "_volcano_untested_rows", "_safe_neg_log10", "_correction_label", "_clean_feature_name", "_gene_tokens",
        "_normalize_highlight_token", "_volcano_condition_texts", "_volcano_marker_style", "_volcano_top_hits",
        "_place_volcano_labels", "_volcano_png_figure", "_volcano_figure"))
    helpers = helpers.replace("_get_plt()", "get_plt()")
    helpers = helpers.replace("_get_plotly()", "get_plotly_go()")
    constants = "\n\n".join(ast.get_source_segment(original, node) for node in ast.parse(original).body
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and any(
            isinstance(part, ast.Name) and part.id.startswith(("VOLCANO_", "_VOLCANO_", "_LABEL_", "CORRECTION_"))
            for part in ast.walk(node)))
    styling = "\n".join(line for line in module_source("plot_styling.py").splitlines() if not line.startswith("from app."))
    styling += "\n\n" + function_definition(module_source("plotting_common.py"), "get_plt")
    styling += "\n\ndef _get_plt():\n    return get_plt()\n"
    styles = extract_notebook_source(styling, ("advanced_label", "advanced_optional_number", "advanced_size",
        "advanced_alpha", "advanced_text", "resolve_marker_shape", "marker_area", "resolve_reference_line",
        "apply_advanced_axes", "advanced_number", "get_plt", "advanced_plotly_layout")).code
    scientific = extract_notebook_source(module_source("functions.py"), ("paired_sample_columns", "resolve_test_type", "effective_test_type",
        "paired_t_test", "imputed_value_counts", "constant_within_group", "constant_differences",
        "without_variation", "comparison_contrast")).code
    core = module_source("stats_core.py").replace("bh_adjust", "_bh_adjust").replace("satterthwaite", "_satterthwaite")
    serialization = extract_notebook_source(module_source("plot_export.py"), ("to_png_bytes", "cm_to_inch")).code
    code = merge_source("import numpy as np\nimport pandas as pd\nfrom typing import Any", scientific, core,
                         styles, serialization, constants, helpers, calculation)
    if interactive:
        common = module_source("plotting_common.py")
        html = function_definition(common, "plotly_html")
        html = replace_once(html, "full_html=False,", "full_html=False, div_id='copylot-plot',\n        post_script=\"window.dispatchEvent(new Event('copylot-plot-ready'));\",")
        code = merge_source(code, html, function_definition(common, "get_plotly"), function_definition(common, "get_plotly_go"),
            extract_notebook_source(module_source("plot_webgl.py"), ("force_svg_rendering",)).code,
            extract_notebook_source(module_source("html_security.py"), ("GENERATED_HTML_META",)).code)
    for before, after in (("AnnotationKind", "str"), ("StatsIdentifier", "str"), ("ResolvedSource", "str"),
                          ("DataSource", "str"), ("_cm_to_inch(", "cm_to_inch(")):
        code = code.replace(before, after)
    roots = (("_volcano_figure", "advanced_plotly_layout", "plotly_html") if interactive
             else ("_volcano_png_figure", "to_png_bytes", "get_plt"))
    return extract_notebook_source(code, ("calculate_table", *roots))


@lru_cache(maxsize=2)
def _volcano_module(interactive=False):
    module = ModuleType(f"_copylot_portable_volcano_{'interactive' if interactive else 'static'}")
    sys.modules[module.__name__] = module
    exec(volcano_source(interactive).code, module.__dict__)
    return module


def render_volcano(payload, *, interactive=False, **options):
    from app.services import stats_tools
    from app.services.annotation_store import get_annotation
    from app.services.dataset_store import get_current_dataset
    from app.services.notebook_provenance import input_history
    from app.services.plot_export import plot_output_format
    from app.services.runtime_cache import runtime_cache_version
    from app.services.session_context import get_session_id

    revision = runtime_cache_version()
    kind = payload.kind
    source, data, metadata, warnings = stats_tools._stats_source(kind, data_source=payload.dataSource)
    data, metadata = data.copy(deep=True), metadata.copy(deep=True)
    annotation, dataset = get_annotation(kind), get_current_dataset(kind)
    lineage, imputation, uses_imputed, imputation_text = input_history(kind, annotation, dataset, source=source)
    mask = stats_tools._imputation_mask(kind, source, data, metadata["sample"].astype(str).tolist())
    metadata = metadata[[column for column in ("sample", "condition", "pair_id") if column in metadata]].copy()
    identifiers = ["GeneNames", "Gene_group", "ProteinNames", "PTM_Collapse_key", "UPD_seq",
                   "Protein_group", "Phosphoprotein", "site_num", "PTM_Collapse_keys"]
    columns = list(dict.fromkeys(metadata["sample"].tolist() + identifiers))
    data = data[[column for column in columns if column in data]].copy()
    calculation = dict(kind=kind, condition1=payload.condition1, condition2=payload.condition2,
        identifier=payload.identifier, p_value_threshold=payload.pValueThreshold,
        log2fc_threshold=payload.log2fcThreshold, test_type=payload.testType,
        use_uncorrected=payload.useUncorrected, data_source=source)
    for key, attribute in (("condition1_control", "condition1Control"), ("condition2_control", "condition2Control")):
        if hasattr(payload, attribute):
            calculation[key] = getattr(payload, attribute)
    # With controls "unpaired" runs as a Welch-type test; record the test that ran.
    calculation["test_type"] = effective_test_type(
        payload.testType, with_controls=bool(calculation.get("condition1_control")) and bool(calculation.get("condition2_control")))
    module = _volcano_module(interactive)
    untested: list = []
    _, label, table, calculation_warnings = module.calculate_table(
        data, metadata, mask, untested_out=untested, **calculation)
    # The same warnings and untested rows a live run returns, so the table read
    # back from this snapshot is the table the page showed.
    warnings = [*warnings, *calculation_warnings]
    bound = inspect.signature(stats_tools.volcano_html if interactive else stats_tools.volcano_png).bind(payload, **options)
    bound.apply_defaults()
    figure_settings = dict(bound.arguments)
    figure_settings.pop("payload")
    figure_settings.update({key: value for key, value in calculation.items()
                           if key not in {"kind", "identifier", "test_type", "data_source"}})
    figure_settings.update(label_column=label, highlight_terms=payload.highlightTerms)
    resources = {"input.parquet": dataframe_bytes(data), "metadata.parquet": dataframe_bytes(metadata),
                 "table.parquet": dataframe_bytes(table), "untested.parquet": dataframe_bytes(untested[0])}
    if interactive:
        figure = module._volcano_figure(table, **figure_settings)
        figure.update_layout(**module.advanced_plotly_layout(figure_settings["advanced"]))
        content = module.plotly_html(figure)
        resources.update({"original.html": content.encode("utf-8"), "figure.json": figure.to_json().encode("utf-8")})
        render_code = (
            "from IPython.display import IFrame\n"
            "figure = functions._volcano_figure(table, **settings['figure'])\n"
            "figure.update_layout(**functions.advanced_plotly_layout(settings['figure']['advanced']))\n"
            "html = functions.plotly_html(figure)\n"
            "assert json.loads(figure.to_json()) == json.loads((RESOURCES / 'figure.json').read_text())\n"
            "Path('reproduced.html').write_text(html, encoding='utf-8', newline='')\n"
            "display(IFrame('reproduced.html', width='100%', height=760))")
    else:
        figure, plt = module._volcano_png_figure(table, **figure_settings)
        fmt = plot_output_format.get()
        format_token = module.plot_output_format.set(fmt)
        try:
            content = module.to_png_bytes(figure, plt, dpi=figure_settings["dpi"])
        finally:
            module.plot_output_format.reset(format_token)
        resources[f"original.{fmt}"] = bytes(content)
        render_code = (
            "from IPython.display import Image\n"
            "figure, plt = functions._volcano_png_figure(table, **settings['figure'])\n"
            "image = functions.to_png_bytes(figure, plt, dpi=settings['figure']['dpi'])\n"
            "Path('reproduced.png').write_bytes(image)\ndisplay(Image(data=image))")
    if mask is not None:
        resources["imputation_mask.parquet"] = dataframe_bytes(mask)
    recipe = NotebookRecipe(
        plot_name=("Interactive " if interactive else "") + ("Control Volcano" if "condition1_control" in calculation else "Volcano Plot"),
        source=volcano_source(interactive), settings={"calculation": calculation, "figure": figure_settings},
        original_filename=dataset.filename, resources=resources,
        uses_imputed_input=uses_imputed, imputation_recipe=imputation_text,
        provenance={"kind": kind, "plot": "volcano", "view": "interactive" if interactive else "static", "sourceUsed": source,
            "request": payload.model_dump(), "labelColumn": label, "warnings": warnings,
            "normalization": annotation.filter_config.normalization,
            "filter": annotation.filter_config.model_dump(),
            "upstreamCollapse": lineage.model_dump() if lineage else None,
            "imputation": imputation.model_dump() if imputation else None},
        input_explanation="This is the exact selected log2 analysis matrix and pairing metadata. "
            "The notebook recalculates the selected comparison, replicate eligibility, t-test, p-value "
            "correction and significance classes before redrawing the figure. The captured imputation mask "
            "reproduces imputed-value counts; no values are drawn again. Normalization, filtering and any "
            "upstream collapse are already reflected in the selected matrix, not rerun from the original upload.",
        calculation="from IPython.display import display\n"
            "mask_path = RESOURCES / 'imputation_mask.parquet'\n"
            "imputation_mask = pd.read_parquet(mask_path) if mask_path.exists() else None\n"
            "_, label_column, table, warnings = functions.calculate_table(data, metadata, imputation_mask, **settings['calculation'])\n"
            "pd.testing.assert_frame_equal(table, pd.read_parquet(RESOURCES / 'table.parquet'), check_exact=True)\n"
            "table.to_csv('reproduced_table.csv', index=False)\ndisplay(table)\n" + render_code,
    )
    try:
        token = capture_notebook(get_session_id(), recipe) if runtime_cache_version() == revision else ""
    except ValueError:
        token = ""
    return content, token
