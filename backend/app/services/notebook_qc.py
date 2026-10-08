"""Exact QC plot/table recipes with live state replaced by explicit inputs.

The notebook's identifier helpers are reused. Rendering/style code is extracted
from the actual UI implementation because the legacy notebook coverage function
does not implement all of its advanced options. No second renderer is maintained.
"""
from __future__ import annotations

import ast
import re
from functools import lru_cache
import inspect
from pathlib import Path
import sys
from types import ModuleType

from app.services.notebook_archive import NotebookRecipe, dataframe_bytes
from app.services.notebook_preprocessing import capture_notebook
from app.services.notebook_source import _bindings, _global_references, _segment, extract_notebook_source
from app.services.notebook_snapshots import NotebookSnapshots

snapshots = NotebookSnapshots()
QC_RENDERERS = {
    "coverage": "qc_coverage_plot", "boxplot": "qc_boxplot_plot", "cv": "qc_cv_plot",
    "histogram": "qc_intensity_histogram_plot", "correlation": "qc_correlation_plot",
    "abundance": "qc_abundance_plot",
}
PAIRED_PLOTS = {"coverage", "boxplot", "cv"}
LINEAR_PLOTS = {"cv", "abundance"}


def _source(name: str) -> str:
    if getattr(sys, "frozen", False):
        path = Path(sys._MEIPASS) / "notebook_sources" / name
    else:
        root = Path(__file__).resolve().parents[3]
        package = name in {"notebook_functions.py", "_core.py"}
        path = root / ("proteomicscopylot" if package else "backend/app/services") / name
    return _inline_core(path.read_text(encoding="utf-8"))


_CORE_BLOCK = re.compile(r"^# <shared-core>.*?^# </shared-core>\n", re.MULTILINE | re.DOTALL)


def _inline_core(text: str) -> str:
    """Replace a module's import of the shared core with the definitions it uses.

    `functions.py`, `stats_core.py` and `notebook_functions.py` import part of
    `proteomicscopylot/_core.py` inside a `# <shared-core>` block. Notebook
    exports must not import the application or the package, so the source they
    are extracted from carries those definitions (and whatever they need from the
    core) in place of the block. Imports the module already makes are not
    repeated.
    """
    match = _CORE_BLOCK.search(text)
    if match is None:
        return text
    wanted = {
        alias.asname or alias.name
        for node in ast.walk(ast.parse(match.group(0)))
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith(("_core", "copylot_core"))
        for alias in node.names
    }
    host = text[:match.start()] + text[match.end():]
    bound = set().union(*(_bindings(node) for node in ast.parse(host).body))
    core = _source("_core.py")
    core_body = ast.parse(core).body
    definitions: dict[str, ast.stmt] = {}
    for node in core_body:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            continue
        for bound_name in _bindings(node):
            definitions[bound_name] = node
    selected: set[ast.stmt] = set()
    required = set(wanted)
    while required:
        node = definitions.get(required.pop())
        if node is None or node in selected:
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)) and _bindings(node) <= bound:
            continue
        selected.add(node)
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            required.update(_global_references(_segment(core, node)) - _bindings(node))
    inlined = "\n\n".join(_segment(core, node) for node in core_body if node in selected)
    return text[:match.start()] + inlined + "\n" + text[match.end():]


def _definition(source: str, name: str) -> str:
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(source, node)


def _replace_once(source: str, before: str, after: str) -> str:
    if source.count(before) != 1:
        raise ValueError("The QC renderer changed; update its notebook adapter before exporting.")
    return source.replace(before, after, 1)


def _merge_source(*sources: str) -> str:
    """Merge trusted subsets while checking that duplicate definitions agree."""
    seen = set()
    nodes = []
    for source in sources:
        for node in ast.parse(source).body:
            if isinstance(node, ast.ImportFrom) and node.module == "__future__":
                continue
            key = ast.dump(node, include_attributes=False)
            if key not in seen:
                seen.add(key)
                nodes.append(_segment(source, node))
    return "\n\n".join(nodes)


@lru_cache(maxsize=6)
def qc_source(plot: str):
    if plot not in QC_RENDERERS:
        raise ValueError("Unsupported notebook plot.")
    rendering = _source("plot_images.py")
    function = _definition(rendering, QC_RENDERERS[plot])
    function = function.replace("_phosprot_values_are_centred(kind)", "centered")
    replacements = [
        (f"def {QC_RENDERERS[plot]}(", "def plot_figure("),
        ("    kind: AnnotationKind,", "    data, metadata, condition_colors," + (" workflow_kind," if plot == "abundance" else "") + " centered=False,"),
        ("plt = _get_plt()", "plt = get_plt()"),
        ("return _to_png_bytes(fig, plt, dpi=dpi" + (", tight=False" if plot == "coverage" else "") + ")", "return fig"),
    ]
    if plot != "abundance":
        replacements.extend([
        (f"frame = {'linear' if plot in LINEAR_PLOTS else 'log2'}_qc_frame(kind)", "frame = data"),
        ("sample_columns = _get_sample_columns(kind, frame)", "sample_columns = metadata['sample'].tolist()"),
        ("_metadata_for_kind(kind, frame, sample_columns)", "metadata.copy()"),
        ])
    else:
        replacements.append(("_abundance_mean_intensities(kind)", "_abundance_mean_intensities(data, metadata, workflow_kind)"))
    if plot not in {"correlation", "abundance"}:
        replacements.append(('raise ValueError(f"No sample columns found for {kind} dataset.")', 'raise ValueError("No annotated sample columns found.")'))
    if plot != "correlation":
        colors = {"cv": "valid_conditions", "histogram": "[condition for condition, _ in mean_intensities]", "abundance": "unique_conditions"}.get(plot, "conditions")
        replacements.append((f"color_map = advanced_condition_colors(kind, plt, {colors}, advanced)", "color_map = condition_colors"))
    for before, after in replacements:
        function = _replace_once(function, before, after)
    function = function.replace("apply(_extract_id_or_number)", "apply(extract_sample_id)")
    function = function.replace("metadata.copy().copy()", "metadata.copy()")
    helpers = "\n\n".join(_definition(rendering, name) for name in (
        "_make_fig", "_grouped_meta_order", "_feature_context", "_quantified_feature_count", "_median_label_y",
        "correlation_matrix_mesh"))
    helpers = helpers.replace("_cm_to_inch(", "cm_to_inch(")
    if plot == "abundance":
        abundance = _definition(rendering, "_abundance_mean_intensities")
        abundance = abundance.replace("    kind: AnnotationKind,", "    data, metadata, kind: str,")
        abundance = abundance.replace("linear_qc_frame(kind)", "data")
        abundance = abundance.replace("_get_sample_columns(kind, frame)", "metadata['sample'].tolist()")
        abundance = abundance.replace("_metadata_for_kind(kind, frame, sample_columns)", "metadata.copy()")
        helpers += "\n\n" + abundance + "\n\n" + _definition(rendering, "_abundance_key_column").replace("AnnotationKind", "str")
    notebook = extract_notebook_source(_source("notebook_functions.py"), ("extract_sample_id",)).code
    styling = _source("plot_styling.py")
    # These three stateful imports are not needed by the selected pure helpers.
    styling = "\n".join(line for line in styling.splitlines() if not line.startswith("from app."))
    styling += "\n\n" + _definition(_source("plotting_common.py"), "get_plt")
    styling += "\n\ndef _get_plt():\n    return get_plt()\n"
    style_roots = ("advanced_anchor", "advanced_color_map", "advanced_label", "advanced_text", "advanced_number", "advanced_label_size",
                   "marker_style", "rename_composite_sample_label", "resolve_reference_line", "apply_advanced_axes")
    styles = extract_notebook_source(styling, (*style_roots, "get_plt")).code
    serialization = extract_notebook_source(_source("plot_export.py"), ("to_png_bytes", "cm_to_inch")).code
    table_code = _table_source(plot) if plot in PAIRED_PLOTS else ""
    scientific_source = _source("functions.py")
    scientific = "\n\n".join(_definition(scientific_source, name) for name in ("raw_zero_to_nan", "condition_cvs", "intensity_unit_label", "abundance_axis_label"))
    combined = _merge_source("import math\nimport numpy as np\nimport pandas as pd\nfrom typing import Any", notebook,
                             styles, serialization, helpers, function, table_code, scientific)
    roots = ("plot_figure", "to_png_bytes", "get_plt") + (("prepare_table",) if plot in PAIRED_PLOTS else ())
    return extract_notebook_source(combined, roots)


def _table_source(plot: str) -> str:
    tables = _source("table_functions.py")
    table_code = "\n\n".join(_definition(tables, node.name) for node in ast.parse(tables).body
                             if isinstance(node, ast.FunctionDef) and not node.name.startswith("qc_"))
    table_function = _definition(tables, f"qc_{plot}_table")
    table_function = table_function.replace(f"qc_{plot}_table(kind: AnnotationKind", "prepare_table(data, metadata")
    table_function = table_function.replace(f"frame = {'linear' if plot == 'cv' else 'log2'}_qc_frame(kind)", "frame = data")
    table_function = table_function.replace("_get_sample_columns(kind, frame)", "metadata['sample'].tolist()")
    table_function = table_function.replace("_metadata_for_kind(kind, frame, sample_columns)", "metadata.copy()")
    table_code += "\n\n" + table_function
    table_code = table_code.replace("_extract_id_or_number", "extract_sample_id")
    return table_code


@lru_cache(maxsize=6)
def _qc_module(plot: str):
    # Only installed, trusted source is compiled; user text remains JSON/data.
    module = ModuleType(f"_copylot_portable_{plot}")
    sys.modules[module.__name__] = module  # Required by dataclass type resolution.
    exec(qc_source(plot).code, module.__dict__)
    return module


def render_qc(kind: str, *, plot: str = "coverage", **options) -> tuple[bytes, str]:
    from app.services.annotation_store import get_annotation
    from app.services.dataset_store import get_current_dataset
    from app.services.data_tools import (log2_qc_frame, linear_qc_frame, linear_qc_uses_unnormalized,
        metadata_for_kind, _get_sample_columns)
    from app.services import plot_images
    from app.services.plot_styling import advanced_condition_colors
    from app.services.plot_export import plot_output_format
    from app.services.session_context import get_session_id
    from app.services.runtime_cache import runtime_cache_version
    from app.services.notebook_provenance import input_history

    if kind not in {"protein", "phospho", "phosprot"} or plot not in QC_RENDERERS:
        raise ValueError("This QC plot/level does not yet have a verified notebook adapter.")
    revision = runtime_cache_version()
    annotation = get_annotation(kind)
    dataset = get_current_dataset(kind)
    if annotation is None or dataset is None:
        raise ValueError("Load and annotate a dataset before plotting.")
    lineage, imputation, uses_imputed_input, imputation_text = input_history(kind, annotation, dataset)
    data = (linear_qc_frame(kind) if plot in LINEAR_PLOTS else log2_qc_frame(kind)).copy(deep=True)
    unnormalized = plot in LINEAR_PLOTS and linear_qc_uses_unnormalized(kind)
    metadata = metadata_for_kind(kind, data, _get_sample_columns(kind, data)).copy(deep=True)
    bound = inspect.signature(getattr(plot_images, QC_RENDERERS[plot])).bind(kind, **options)
    bound.apply_defaults()
    settings = dict(bound.arguments)
    settings.pop("kind")
    settings["centered"] = bool(lineage and lineage.aggregation == "robust_site_median")
    module = _qc_module(plot)
    table_settings = {key: settings[key] for key in ("summary", "mode") if key in settings}
    table = module.prepare_table(data, metadata, **table_settings) if plot in PAIRED_PLOTS else None
    conditions = (table["Condition"].astype(str).tolist() if plot == "cv" and not table.empty
                  else metadata["condition"].astype(str).drop_duplicates().tolist())
    if plot == "histogram":
        conditions = [condition for condition in conditions if module.np.isfinite(
            data[metadata.loc[metadata["condition"] == condition, "sample"].tolist()]
            .apply(module.pd.to_numeric, errors="coerce").mean(axis=1).to_numpy(dtype=float)).any()]
    elif plot == "abundance":
        settings["workflow_kind"] = kind
        _, conditions, _, _ = module._abundance_mean_intensities(data, metadata, kind)
    settings["condition_colors"] = advanced_condition_colors(
        kind, module.get_plt(), conditions, settings["advanced"])
    figure = module.plot_figure(data, metadata, **settings)
    fmt = plot_output_format.get()
    format_token = module.plot_output_format.set(fmt)
    try:
        content = module.to_png_bytes(figure, module.get_plt(), dpi=settings["dpi"], tight=plot != "coverage")
    finally:
        module.plot_output_format.reset(format_token)
    plot_name = ({"coverage": "Coverage Summary" if settings.get("summary") else "Coverage Plot",
                  "boxplot": "Intensity Boxplot", "cv": "Coefficient of Variation",
                  "histogram": "Intensity Distribution", "correlation": "Sample Correlation",
                  "abundance": "Abundance Plot"})[plot]
    resources = {"input.parquet": dataframe_bytes(data), "metadata.parquet": dataframe_bytes(metadata), f"original.{fmt}": bytes(content)}
    table_calculation = ""
    if table is not None:
        resources["table.parquet"] = dataframe_bytes(table)
        table_calculation = (
            "\ntable_options = {key: settings[key] for key in ('summary', 'mode') if key in settings}\n"
            "table = functions.prepare_table(data, metadata, **table_options)\n"
            "pd.testing.assert_frame_equal(table, pd.read_parquet(RESOURCES / 'table.parquet'), check_exact=True)\n"
            "table.to_csv('reproduced_table.csv', index=False)\ndisplay(table)")
    recipe = NotebookRecipe(
        plot_name=plot_name, source=qc_source(plot),
        settings=settings, original_filename=dataset.filename,
        provenance={"kind": kind, "plot": plot,
                    "inputScale": ("linear ratios" if plot in LINEAR_PLOTS else "site-centered log2 ratios")
                        if settings["centered"] else ("linear" if plot in LINEAR_PLOTS else "log2"),
                    "upstreamCollapse": lineage.model_dump() if lineage else None,
                    "imputation": imputation.model_dump() if imputation else None,
                    "dataSource": "data", "isLog2Transformed": annotation.is_log2_transformed,
                    "filter": annotation.filter_config.model_dump() if annotation.filter_config else None,
                    "filterAppliedToThisPlot": False, "filterScope": "after_collapse" if lineage else "within_this_annotation",
                    "imputationAppliedToThisPlot": uses_imputed_input,
                    "linearQcUnnormalized": unnormalized,
                    "outputs": ["plot", "table"] if table is not None else ["plot"],
                    "renderer": "Exact UI QC renderer with portable inputs; notebook identifier helpers"},
        resources=resources,
        uses_imputed_input=uses_imputed_input, imputation_recipe=imputation_text,
        calculation="from IPython.display import Image, display\n"
                    "figure = functions.plot_figure(data, metadata, **settings)\n"
                    f"image = functions.to_png_bytes(figure, functions.get_plt(), dpi=settings['dpi'], tight={plot != 'coverage'})\n"
                    "Path('reproduced.png').write_bytes(image)\ndisplay(Image(data=image))\n\n"
                    + table_calculation,
        input_explanation=("The exact collapsed phosphoprotein Data matrix is included, without post-collapse filtering. "
                          "Upstream normalization, filtering and any imputation are documented in upstreamCollapse; collapse is not rerun. "
                          if lineage else f"This export freezes the {'unnormalized (VSN output is not a linear intensity)' if unnormalized else 'normalized'}, unfiltered, non-imputed {'linear' if plot in LINEAR_PLOTS else 'log2'} Data matrix used by the figure. ") +
                          "It does not rerun normalization, filtering or imputation. Original-file preprocessing replay is not yet included.",
    )
    try:
        # Never publish provenance captured across a concurrent dataset edit.
        token = capture_notebook(get_session_id(), recipe) if runtime_cache_version() == revision else ""
    except ValueError:
        # Snapshot memory limits must not break an otherwise valid plot.
        token = ""
    return content, token
