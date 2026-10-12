"""Portable interactive abundance figures from the same UI implementation."""
from functools import lru_cache
import inspect
import sys
from types import ModuleType

from app.services.notebook_archive import NotebookRecipe, dataframe_bytes
from app.services.notebook_preprocessing import capture_notebook
from app.services.notebook_qc import qc_source
from app.services.notebook_source import extract_notebook_source, function_definition, merge_source, module_source, replace_once


@lru_cache(maxsize=1)
def abundance_source():
    shared = extract_notebook_source(qc_source("abundance").code,
                                    ("_abundance_mean_intensities", "abundance_axis_label")).code
    rendering = module_source("plot_images.py")
    ranks = function_definition(rendering, "_abundance_rank_frame")
    ranks = ranks.replace("kind: AnnotationKind", "data, metadata, kind: str")
    ranks = ranks.replace("_abundance_mean_intensities(kind)", "_abundance_mean_intensities(data, metadata, kind)")
    figure = function_definition(rendering, "qc_abundance_interactive_html")
    for before, after in (
        ("def qc_abundance_interactive_html(", "def plot_figure("),
        ("    kind: AnnotationKind,", "    data, metadata, workflow_kind, condition_colors, centered=False,"),
        ("_get_plotly()", "get_plotly()"),
        ("_abundance_rank_frame(kind)", "_abundance_rank_frame(data, metadata, workflow_kind)"),
        ("advanced_condition_colors(kind, None, visible_conditions, advanced)", "condition_colors"),
        ("phosprot_values_are_centred(kind)", "centered"),
        ("return _plotly_html(fig)", "return force_svg_rendering(fig)"),
    ):
        figure = replace_once(figure, before, after)
    figure = figure.replace("_cm_to_px(", "cm_to_px(").replace(") -> str:", "):")
    styles = "\n".join(line for line in module_source("plot_styling.py").splitlines() if not line.startswith("from app."))
    styles = extract_notebook_source(styles, ("advanced_label", "apply_plotly_group_markers", "advanced_plotly_layout")).code
    common = module_source("plotting_common.py")
    html = function_definition(common, "plotly_html")
    html = html.replace("full_html=False,", "full_html=False, div_id='copylot-plot',\n        post_script=\"window.dispatchEvent(new Event('copylot-plot-ready'));\",")
    sources = merge_source(shared, ranks, figure, styles, function_definition(common, "get_plotly"), html,
        extract_notebook_source(module_source("plot_export.py"), ("cm_to_px",)).code,
        extract_notebook_source(module_source("plot_webgl.py"), ("force_svg_rendering",)).code,
        extract_notebook_source(module_source("html_security.py"), ("GENERATED_HTML_META",)).code)
    return extract_notebook_source(sources, ("plot_figure", "plotly_html"))


@lru_cache(maxsize=1)
def _abundance_module():
    module = ModuleType("_copylot_portable_interactive_abundance")
    sys.modules[module.__name__] = module
    exec(abundance_source().code, module.__dict__)
    return module


def render_abundance(kind: str, **options) -> tuple[str, str]:
    from app.services.data_tools import linear_qc_frame, linear_qc_uses_unnormalized, metadata_for_kind, _get_sample_columns
    from app.services.dataset_store import get_current_dataset
    from app.services.plot_images import qc_abundance_interactive_html
    from app.services.plot_styling import advanced_condition_colors
    from app.services.runtime_cache import runtime_cache_version
    from app.services.session_context import get_session_id
    from app.services.annotation_store import get_annotation
    from app.services.notebook_provenance import input_history

    if kind not in {"protein", "phospho", "phosprot"}:
        raise ValueError("This interactive level is not yet supported for notebook export.")
    revision = runtime_cache_version()
    dataset = get_current_dataset(kind)
    if dataset is None:
        raise ValueError("Load and annotate a dataset first.")
    lineage, imputation, uses_imputed_input, imputation_text = input_history(kind, get_annotation(kind), dataset)
    data = linear_qc_frame(kind).copy(deep=True)
    unnormalized = linear_qc_uses_unnormalized(kind)
    metadata = metadata_for_kind(kind, data, _get_sample_columns(kind, data)).copy(deep=True)
    bound = inspect.signature(qc_abundance_interactive_html).bind(kind, **options)
    bound.apply_defaults()
    settings = dict(bound.arguments)
    settings.pop("kind")
    settings["workflow_kind"] = kind
    settings["centered"] = bool(lineage and lineage.aggregation == "robust_site_median")
    module = _abundance_module()
    ranks, _, _ = module._abundance_rank_frame(data, metadata, kind)
    if settings["condition"] != "All Conditions":
        ranks = ranks[ranks["Condition"] == settings["condition"]]
    conditions = ranks["Condition"].astype(str).dropna().unique().tolist()
    settings["condition_colors"] = advanced_condition_colors(kind, None, conditions, settings["advanced"])
    figure = module.plot_figure(data, metadata, **settings)
    html = module.plotly_html(figure)
    recipe = NotebookRecipe(
        plot_name="Interactive Abundance", source=abundance_source(), settings=settings,
        original_filename=dataset.filename,
        provenance={"kind": kind, "plot": "abundance", "view": "interactive", "inputScale": "linear ratios" if settings["centered"] else "linear",
                    "upstreamCollapse": lineage.model_dump() if lineage else None,
                    "imputation": imputation.model_dump() if imputation else None,
                    "dataSource": "data", "filterAppliedToThisPlot": False, "filterScope": "after_collapse" if lineage else "within_this_annotation",
                    "imputationAppliedToThisPlot": uses_imputed_input,
                    "linearQcUnnormalized": unnormalized,
                    "outputs": ["interactive plot"]},
        uses_imputed_input=uses_imputed_input, imputation_recipe=imputation_text,
        resources={"input.parquet": dataframe_bytes(data), "metadata.parquet": dataframe_bytes(metadata),
                   "figure.json": figure.to_json().encode(), "original.html": html.encode()},
        calculation="from IPython.display import IFrame, display\n"
                    "figure = functions.plot_figure(data, metadata, **settings)\n"
                    "assert json.loads(figure.to_json()) == json.loads((RESOURCES / 'figure.json').read_text())\n"
                    "Path('reproduced.html').write_text(functions.plotly_html(figure), encoding='utf-8', newline='')\n"
                    "display(IFrame('reproduced.html', width='100%', height=600))",
        input_explanation=("The exact collapsed phosphoprotein matrix on linear scale is included, without post-collapse filtering. "
                          "Upstream processing and any imputation are recorded in upstreamCollapse; collapse is not rerun. "
                          if lineage else f"The exact {'unnormalized (VSN output is not a linear intensity)' if unnormalized else 'normalized'}, unfiltered, non-imputed linear matrix is included. ") +
                          "The notebook recalculates abundance ranks and verifies every Plotly trace and layout value. "
                          "Plotly JavaScript is embedded for offline viewing. Original-file preprocessing replay is not yet included.",
    )
    try:
        token = capture_notebook(get_session_id(), recipe) if runtime_cache_version() == revision else ""
    except ValueError:
        token = ""
    return html, token
