"""Portable peptide plots from captured explicit inputs."""
from functools import lru_cache
import inspect
import sys
from types import ModuleType

from app.services.notebook_archive import NotebookRecipe, dataframe_bytes
from app.services.notebook_preprocessing import capture_notebook
from app.services.notebook_interactive import abundance_source
from app.services.notebook_qc import qc_source
from app.services.notebook_source import extract_notebook_source, function_definition, merge_source, module_source, replace_once


@lru_cache(maxsize=1)
def missed_cleavage_source():
    original = module_source('peptide_tools.py')
    function = function_definition(original, 'peptide_missed_cleavage_plot')
    start = function.index('    plt = _get_plt()')
    boundary = function.index('    summary = peptide_missed_cleavage_summary(')
    preparation = ('def prepare_input(frame, meta):\n' + function[function.index('    file_col ='):boundary]
                   + '    return wide[[seq_col, *annotated_cols]], seq_col\n')
    figure = function[:start] + ('    plt = get_plt()\n    wide = data\n    meta = metadata\n'
        '    annotated_cols = [column for column in meta["new_sample"] if column in wide.columns]\n') + function[boundary:]
    figure = replace_once(figure, 'def peptide_missed_cleavage_plot(\n    *,',
                           'def render_plot(data, metadata, *, seq_col,')
    figure = figure.replace('_cm_to_inch(', 'cm_to_inch(').replace('_to_png_bytes(', 'to_png_bytes(')
    source = merge_source('import numpy as np\nimport pandas as pd\nfrom matplotlib import ticker as mtick',
        extract_notebook_source(original, ('peptide_missed_cleavage_summary', 'PROTEASE_LABELS',
                                          '_stripped_sequence_column', '_require_column')).code,
        extract_notebook_source(modification_source().code, ('_file_name_column', '_sample_rename_map')).code,
        extract_notebook_source(qc_source('coverage').code,
            ('get_plt', 'to_png_bytes', 'cm_to_inch', 'apply_advanced_axes', 'advanced_label_size')).code,
        preparation, figure)
    return extract_notebook_source(source, ('prepare_input', 'render_plot', 'peptide_missed_cleavage_summary'))


@lru_cache(maxsize=1)
def _missed_cleavage_module():
    module = ModuleType('_copylot_portable_missed_cleavage')
    sys.modules[module.__name__] = module
    exec(missed_cleavage_source().code, module.__dict__)
    return module


def render_missed_cleavage(**options):
    from app.services import peptide_tools
    from app.services.dataset_store import get_current_dataset
    from app.services.plot_export import plot_output_format
    from app.services.runtime_cache import runtime_cache_version
    from app.services.session_context import get_session_id

    revision = runtime_cache_version()
    bound = inspect.signature(peptide_tools.peptide_missed_cleavage_plot).bind(**options)
    bound.apply_defaults()
    settings = dict(bound.arguments)
    settings['protease'] = peptide_tools.normalize_protease(settings['protease'])
    frame = peptide_tools.get_peptide_frame()
    metadata = peptide_tools._prepare_metadata(frame, settings['include_id'])
    module = _missed_cleavage_module()
    data, settings['seq_col'] = module.prepare_input(frame, metadata)
    metadata = metadata[['condition', 'new_sample']].copy(deep=True)
    summary = module.peptide_missed_cleavage_summary(data, sequence_column=settings['seq_col'],
        sample_columns=[s for s in metadata['new_sample'] if s in data.columns], protease=settings['protease'])
    fmt = plot_output_format.get()
    format_token = module.plot_output_format.set(fmt)
    try:
        image = module.render_plot(data, metadata, **settings)
    finally:
        module.plot_output_format.reset(format_token)
    recipe = NotebookRecipe(plot_name='Peptide Missed Cleavages',
        source=extract_notebook_source(missed_cleavage_source().code, ('render_plot', 'peptide_missed_cleavage_summary')),
        settings=settings, original_filename=get_current_dataset('peptide').filename,
        resources={'input.parquet': dataframe_bytes(data), 'metadata.parquet': dataframe_bytes(metadata),
            'summary.parquet': dataframe_bytes(summary), f'original.{fmt}': bytes(image)},
        provenance={'kind': 'peptide', 'plot': 'missed_cleavages', 'protease': settings['protease'],
            'aggregation': 'maximum quantity per stripped sequence/run',
            'metadataSource': 'protein annotation' if get_current_dataset('protein') is not None else 'peptide annotation',
            'normalizationApplied': False, 'filterApplied': False, 'imputationApplied': False},
        input_explanation='The captured matrix contains maximum quantities per stripped sequence/run, mapped to '
            'the exact annotated display samples; raw run paths are omitted. The notebook repeats detection, '
            'unique-sequence counting and the selected protease rules, excluding C-terminal cleavage sites. '
            'Zero and non-finite quantities are missing. Percentages use each sample\'s detected unique sequences; '
            'the optional text sums all classes with at least one missed cleavage. No normalization or imputation applies.',
        calculation="from IPython.display import Image, display\n"
            "samples = [s for s in metadata['new_sample'] if s in data.columns]\n"
            "summary = functions.peptide_missed_cleavage_summary(data, sequence_column=settings['seq_col'], sample_columns=samples, protease=settings['protease'])\n"
            "pd.testing.assert_frame_equal(summary, pd.read_parquet(RESOURCES / 'summary.parquet'), check_exact=True)\n"
            "summary.to_csv('reproduced_missed_cleavages.csv', index=False)\ndisplay(summary)\n"
            "image = functions.render_plot(data, metadata, **settings)\n"
            "Path('reproduced.png').write_bytes(image)\ndisplay(Image(data=image))")
    try:
        token = capture_notebook(get_session_id(), recipe) if runtime_cache_version() == revision else ''
    except ValueError:
        token = ''
    return image, token


@lru_cache(maxsize=1)
def modification_source():
    original = module_source('peptide_tools.py')
    function = function_definition(original, 'peptide_modification_plot')
    start = function.index('    plt = _get_plt()')
    boundary = function.index('    modification_counts = peptide_modification_counts(')
    preparation = ('def prepare_input(frame, meta):\n' + function[function.index('    file_col ='):boundary]
                   + '    return filtered\n')
    figure = function[:start] + ('    plt = get_plt()\n    filtered = data\n'
        '    ordered_samples = metadata["new_sample"].tolist()\n'
        '    annotated_cols = [column for column in ordered_samples if column in filtered.columns]\n') + function[boundary:]
    figure = replace_once(figure, 'def peptide_modification_plot(\n    *,', 'def render_plot(data, metadata, *,')
    figure = figure.replace('_cm_to_inch(', 'cm_to_inch(').replace('_to_png_bytes(', 'to_png_bytes(')
    helpers = '\n\n'.join(function_definition(original, name) for name in
        ('_file_name_column', '_require_column', '_sample_rename_map'))
    helpers = helpers.replace('_extract_id_or_number(', 'extract_sample_id(')
    source = merge_source('import numpy as np\nimport pandas as pd', preparation, figure, helpers,
        extract_notebook_source(original, ('peptide_modification_counts',)).code,
        extract_notebook_source(module_source('functions.py'), ('sample_id_map', 'extract_sample_id')).code,
        extract_notebook_source(rt_source().code,
            ('get_plt', 'to_png_bytes', 'cm_to_inch', 'apply_advanced_axes')).code)
    return extract_notebook_source(source, ('prepare_input', 'render_plot', 'peptide_modification_counts'))


@lru_cache(maxsize=1)
def _modification_module():
    module = ModuleType('_copylot_portable_peptide_modification')
    sys.modules[module.__name__] = module
    exec(modification_source().code, module.__dict__)
    return module


def render_modification(**options):
    from app.services import peptide_tools
    from app.services.dataset_store import get_current_dataset
    from app.services.plot_export import plot_output_format
    from app.services.runtime_cache import runtime_cache_version
    from app.services.session_context import get_session_id

    revision = runtime_cache_version()
    dataset = get_current_dataset('peptide')
    bound = inspect.signature(peptide_tools.peptide_modification_plot).bind(**options)
    bound.apply_defaults()
    settings = dict(bound.arguments)
    frame = peptide_tools.get_peptide_frame()
    metadata = peptide_tools._prepare_metadata(frame, settings['include_id'])
    module = _modification_module()
    data = module.prepare_input(frame, metadata)
    metadata = metadata[['condition', 'new_sample']].copy(deep=True)
    counts = module.peptide_modification_counts(data, sequence_column='Modified.Sequence',
        sample_columns=[s for s in metadata['new_sample'] if s in data.columns])
    fmt = plot_output_format.get()
    format_token = module.plot_output_format.set(fmt)
    try:
        image = module.render_plot(data, metadata, **settings)
    finally:
        module.plot_output_format.reset(format_token)
    recipe = NotebookRecipe(plot_name='Peptide Modifications',
        source=extract_notebook_source(modification_source().code, ('render_plot', 'peptide_modification_counts')),
        settings=settings, original_filename=dataset.filename,
        resources={'input.parquet': dataframe_bytes(data), 'metadata.parquet': dataframe_bytes(metadata),
            'counts.parquet': dataframe_bytes(counts), f'original.{fmt}': bytes(image)},
        provenance={'kind': 'peptide', 'plot': 'modifications', 'aggregation': 'maximum quantity per modified sequence/run',
            'metadataSource': 'protein annotation' if get_current_dataset('protein') is not None else 'peptide annotation',
            'normalizationApplied': False, 'filterApplied': False, 'imputationApplied': False},
        input_explanation='The captured matrix contains the maximum Precursor.Quantity per modified sequence/run, '
            'mapped to the exact annotated display samples by the application. Raw run paths are omitted. '
            'The notebook reruns the same modification classification and detection rules: zero and non-finite '
            'quantities are missing; a sequence counts once per modification class/sample, even with repeated '
            'modifications. A sequence can belong to multiple classes. No normalization or imputation applies.',
        calculation="from IPython.display import Image, display\n"
            "samples = [s for s in metadata['new_sample'] if s in data.columns]\n"
            "counts = functions.peptide_modification_counts(data, sequence_column='Modified.Sequence', sample_columns=samples)\n"
            "pd.testing.assert_frame_equal(counts, pd.read_parquet(RESOURCES / 'counts.parquet'), check_exact=True)\n"
            "counts.to_csv('reproduced_modification_counts.csv', index=True)\ndisplay(counts)\n"
            "image = functions.render_plot(data, metadata, **settings)\n"
            "Path('reproduced.png').write_bytes(image)\ndisplay(Image(data=image))")
    try:
        token = capture_notebook(get_session_id(), recipe) if runtime_cache_version() == revision else ''
    except ValueError:
        token = ''
    return image, token


@lru_cache(maxsize=1)
def interactive_rt_source():
    original = module_source('peptide_tools.py')
    function = function_definition(original, 'peptide_rt_interactive_html')
    start = function.index('    _require_column(frame, "Predicted.RT")')
    boundary = function.index('    if len(data) > 250_000:')
    preparation = ('def prepare_points(frame):\n' + function[start:boundary]
                   + "    return data.drop(columns=['sample'])\n")
    rendering = ('def plot_figure(data, *, add_line=False, header=True, sampling_seed=69, '
                 'width_cm=20, height_cm=15, advanced=None):\n    go = get_plotly()[1]\n'
                 + function[boundary:])
    rendering = replace_once(rendering, 'return _plotly_html(fig)', 'return force_svg_rendering(fig)')
    rendering = rendering.replace('_cm_to_px(', 'cm_to_px(')
    helpers = '\n\n'.join(function_definition(original, name) for name in
        ('_require_column', '_peptide_feature_column', '_file_name_column', '_short_sample_label'))
    helpers = helpers.replace('_truncate_hover_text(', 'truncate_hover_text(')
    preparation = preparation.replace('_truncate_hover_text(', 'truncate_hover_text(')
    styling = '\n'.join(line for line in module_source('plot_styling.py').splitlines() if not line.startswith('from app.'))
    sources = merge_source('import re\nimport numpy as np\nimport pandas as pd',
        extract_notebook_source(abundance_source().code,
            ('get_plotly', 'plotly_html', 'force_svg_rendering', 'cm_to_px', 'advanced_plotly_layout')).code,
        extract_notebook_source(styling, ('plotly_marker', 'resolve_reference_line')).code,
        function_definition(module_source('plotting_common.py'), 'truncate_hover_text'), helpers, preparation, rendering)
    return extract_notebook_source(sources, ('prepare_points', 'plot_figure', 'plotly_html'))


@lru_cache(maxsize=1)
def _interactive_rt_module():
    module = ModuleType('_copylot_portable_interactive_rt')
    sys.modules[module.__name__] = module
    exec(interactive_rt_source().code, module.__dict__)
    return module


def render_interactive_rt(**options):
    import pandas as pd
    from app.services.dataset_store import get_current_dataset
    from app.services.peptide_tools import get_peptide_frame, peptide_rt_interactive_html
    from app.services.runtime_cache import runtime_cache_version
    from app.services.session_context import get_session_id

    revision = runtime_cache_version()
    dataset = get_current_dataset('peptide')
    bound = inspect.signature(peptide_rt_interactive_html).bind(**options)
    bound.apply_defaults()
    settings = dict(bound.arguments)
    module = _interactive_rt_module()
    data = module.prepare_points(get_peptide_frame())
    figure = module.plot_figure(data, **settings)
    html = module.plotly_html(figure)
    recipe = NotebookRecipe(plot_name='Interactive Peptide Retention Time',
        source=extract_notebook_source(interactive_rt_source().code, ('plot_figure', 'plotly_html')),
        settings=settings, original_filename=dataset.filename,
        resources={'input.parquet': dataframe_bytes(data), 'metadata.parquet': dataframe_bytes(pd.DataFrame()),
            'figure.json': figure.to_json().encode(), 'original.html': html.encode()},
        provenance={'kind': 'peptide', 'plot': 'retention_time', 'view': 'interactive',
            'normalizationApplied': False, 'filterApplied': False, 'imputationApplied': False,
            'validPairs': len(data), 'displayedPoints': len(figure.data[0].x),
            'samplingSeed': settings['sampling_seed'], 'sampleLimit': 250000,
            'inputBoundary': 'Numeric complete RT pairs with original feature and shortened hover labels'},
        input_explanation='The exact valid retention-time pairs and displayed hover labels are captured before '
            'scatter sampling. Numeric conversion, missing-pair exclusion, feature selection/fallback identifiers, '
            'shortened labels and Actual - Predicted differences were prepared by the app. Full run paths are '
            'omitted. No intensity normalization, filtering or imputation applies. The notebook repeats sampling '
            'above 250,000 pairs with the recorded seed, applies the same SVG rendering safeguards, '
            'and verifies every trace and layout value. '
            'Plotly JavaScript is embedded for offline viewing.',
        calculation="from IPython.display import IFrame, display\n"
            "figure = functions.plot_figure(data, **settings)\n"
            "assert json.loads(figure.to_json()) == json.loads((RESOURCES / 'figure.json').read_text())\n"
            "Path('reproduced.html').write_text(functions.plotly_html(figure), encoding='utf-8', newline='')\n"
            "display(IFrame('reproduced.html', width='100%', height=600))")
    try:
        token = capture_notebook(get_session_id(), recipe) if runtime_cache_version() == revision else ''
    except ValueError:
        token = ''
    return html, token


@lru_cache(maxsize=1)
def rt_source():
    original = module_source('peptide_tools.py')
    figure = function_definition(original, 'peptide_rt_plot')
    for before, after in (
        ('def peptide_rt_plot(\n    *,', 'def render_plot(frame, *,'),
        ('    frame = get_peptide_frame()\n', ''),
        ('_get_plt()', 'get_plt()'),
        ('_cm_to_inch(', 'cm_to_inch('),
        ('_to_png_bytes(', 'to_png_bytes('),
    ):
        if before == '_cm_to_inch(':
            figure = figure.replace(before, after)
        else:
            figure = replace_once(figure, before, after)
    helpers = extract_notebook_source(qc_source('coverage').code,
        ('get_plt', 'to_png_bytes', 'cm_to_inch', 'resolve_reference_line', 'apply_advanced_axes')).code
    styling = '\n'.join(line for line in module_source('plot_styling.py').splitlines()
                        if not line.startswith('from app.'))
    markers = extract_notebook_source(styling, ('marker_style',)).code
    return extract_notebook_source(merge_source('import pandas as pd', helpers, markers,
        function_definition(original, '_require_column'), figure), ('render_plot',))


@lru_cache(maxsize=1)
def _rt_module():
    module = ModuleType('_copylot_portable_peptide_rt')
    sys.modules[module.__name__] = module
    exec(rt_source().code, module.__dict__)
    return module


def render_rt(**options):
    from app.services.dataset_store import get_current_dataset
    from app.services.peptide_tools import get_peptide_frame, peptide_rt_plot, _require_column
    from app.services.plot_export import plot_output_format
    from app.services.runtime_cache import runtime_cache_version
    from app.services.session_context import get_session_id
    import pandas as pd

    revision = runtime_cache_version()
    dataset = get_current_dataset('peptide')
    frame = get_peptide_frame()
    for column in ('Predicted.RT', 'RT'):
        _require_column(frame, column)
    frame = frame[['Predicted.RT', 'RT']].copy(deep=True)
    bound = inspect.signature(peptide_rt_plot).bind(**options)
    bound.apply_defaults()
    settings = dict(bound.arguments)
    module = _rt_module()
    fmt = plot_output_format.get()
    format_token = module.plot_output_format.set(fmt)
    try:
        content = module.render_plot(frame, **settings)
    finally:
        module.plot_output_format.reset(format_token)
    recipe = NotebookRecipe(plot_name='Peptide Retention Time', source=rt_source(),
        settings=settings, original_filename=dataset.filename,
        resources={'input.parquet': dataframe_bytes(frame), 'metadata.parquet': dataframe_bytes(pd.DataFrame()),
                   f'original.{fmt}': bytes(content)},
        provenance={'kind': 'peptide', 'plot': 'retention_time', 'source': 'uploaded retention-time columns',
            'normalizationApplied': False, 'filterApplied': False, 'imputationApplied': False,
            'scatterSampleLimit': 100000, 'samplingSeed': settings['sampling_seed']},
        input_explanation='The original Predicted.RT and RT columns are captured without intensity normalization, '
            'filtering or imputation. The notebook repeats numeric conversion and missing-pair exclusion. '
            'Static scatter plots above 100,000 valid pairs repeat the app sampling with the recorded seed; '
            'density and hexbin plots use all valid pairs. Only the two needed columns are included.',
        calculation="from IPython.display import Image, display\n"
            "image = functions.render_plot(data, **settings)\n"
            "Path('reproduced.png').write_bytes(image)\ndisplay(Image(data=image))")
    try:
        token = capture_notebook(get_session_id(), recipe) if runtime_cache_version() == revision else ''
    except ValueError:
        token = ''
    return content, token


@lru_cache(maxsize=1)
def coverage_source():
    rendering = module_source("plot_images.py")
    figure = function_definition(rendering, "qc_peptide_coverage_plot")
    for before, after in (
        ("def qc_peptide_coverage_plot(", "def plot_figure(data, metadata, condition_colors,"),
        ("_get_plt()", "get_plt()"),
        ("_peptide_coverage_summary(include_id, quantity_column, level)", "summarize_peptide_coverage(data, metadata)"),
        ('advanced_condition_colors("protein", plt, ordered_conditions, advanced)', "condition_colors"),
        ("return _to_png_bytes(fig, plt, dpi=dpi)", "return fig"),
    ):
        figure = replace_once(figure, before, after)
    helpers = extract_notebook_source(qc_source("coverage").code, (
        "get_plt", "to_png_bytes", "_make_fig", "advanced_anchor", "advanced_label",
        "resolve_reference_line", "apply_advanced_axes")).code
    combined = merge_source(helpers, "import pandas as pd\nfrom typing import Any",
        function_definition(rendering, "summarize_peptide_coverage"), figure)
    return extract_notebook_source(combined, ("plot_figure", "summarize_peptide_coverage", "to_png_bytes", "get_plt"))


@lru_cache(maxsize=1)
def _coverage_module():
    module = ModuleType("_copylot_portable_peptide_coverage")
    sys.modules[module.__name__] = module
    exec(coverage_source().code, module.__dict__)
    return module


def render_coverage(**options):
    from app.services.dataset_store import get_current_dataset
    from app.services.plot_images import qc_peptide_coverage_plot, _peptide_coverage_data
    from app.services.plot_styling import advanced_condition_colors
    from app.services.plot_export import plot_output_format
    from app.services.runtime_cache import runtime_cache_version
    from app.services.session_context import get_session_id

    revision = runtime_cache_version()
    dataset = get_current_dataset("peptide")
    if dataset is None:
        raise ValueError("Load a peptide dataset first.")
    bound = inspect.signature(qc_peptide_coverage_plot).bind(**options)
    bound.apply_defaults()
    settings = dict(bound.arguments)
    data, metadata = _peptide_coverage_data(settings["include_id"], settings["quantity_column"], settings["level"])
    # Raw run paths are unnecessary: the matrix already uses the plotted sample labels.
    metadata = metadata[["label", "condition"]].copy()
    settings["quantity_column"] = data.attrs["quantity_column"]
    module = _coverage_module()
    settings["condition_colors"] = advanced_condition_colors("protein", module.get_plt(),
        metadata["condition"].astype(str).drop_duplicates().tolist(), settings["advanced"])
    figure = module.plot_figure(data, metadata, **settings)
    fmt = plot_output_format.get()
    format_token = module.plot_output_format.set(fmt)
    try:
        content = module.to_png_bytes(figure, module.get_plt(), dpi=settings["dpi"])
    finally:
        module.plot_output_format.reset(format_token)
    table, total, _ = module.summarize_peptide_coverage(data, metadata)
    recipe = NotebookRecipe(
        plot_name=f"{settings['level'].capitalize()} Coverage", source=coverage_source(), settings=settings,
        original_filename=dataset.filename,
        provenance={"kind": settings["level"], "plot": "coverage", "inputScale": "linear",
            "dataSource": "quantified feature-by-sample matrix", "featureColumn": data.attrs["feature_column"],
            "quantityColumn": settings["quantity_column"], "aggregation": "maximum quantity per feature/run",
            "missingValues": "zero and non-finite quantities are missing",
            "totalQuantifiedFeatures": total, "filterAppliedToThisPlot": False,
            "imputationAppliedToThisPlot": False, "outputs": ["plot", "coverage counts"]},
        resources={"input.parquet": dataframe_bytes(data), "metadata.parquet": dataframe_bytes(metadata),
            "table.parquet": dataframe_bytes(table), f"original.{fmt}": bytes(content)},
        calculation="from IPython.display import Image, display\n"
            "table, total, _ = functions.summarize_peptide_coverage(data, metadata)\n"
            "pd.testing.assert_frame_equal(table, pd.read_parquet(RESOURCES / 'table.parquet'), check_exact=True)\n"
            "table.to_csv('reproduced_table.csv', index=False)\ndisplay(table)\n"
            "figure = functions.plot_figure(data, metadata, **settings)\n"
            "image = functions.to_png_bytes(figure, functions.get_plt(), dpi=settings['dpi'])\n"
            "Path('reproduced.png').write_bytes(image)\ndisplay(Image(data=image))",
        input_explanation="The selected quantity is aggregated by maximum per feature/run, then zero and non-finite "
            "values are treated as missing. This export captures that exact annotated matrix, with the plotted sample "
            "labels. It recalculates per-sample detection and the union across selected samples. Peptides are grouped "
            "by stripped sequence; precursors by the recorded precursor identifier. No filtering or imputation is applied. "
            "Original-file preprocessing replay is not yet included.",
    )
    try:
        token = capture_notebook(get_session_id(), recipe) if runtime_cache_version() == revision else ""
    except ValueError:
        token = ""
    return content, token
