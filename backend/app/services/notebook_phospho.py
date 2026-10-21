"""Phospho-specific count and coverage replay from localization-selected rows."""
from functools import lru_cache
import inspect
import sys
from types import ModuleType

from app.services.notebook_archive import NotebookRecipe, dataframe_bytes
from app.services.notebook_preprocessing import capture_notebook
from app.services.notebook_qc import qc_source
from app.services.notebook_source import extract_notebook_source, function_definition, merge_source, module_source, replace_once


@lru_cache(maxsize=1)
def count_source():
    original = module_source('phospho_tools.py')
    table = function_definition(original, 'phosphosite_plot_table')
    table = replace_once(table, 'def phosphosite_plot_table()', 'def prepare_table(data)')
    table = replace_once(table, '    filtered, _, _ = _phospho_context()', '    filtered = data')
    figure = function_definition(original, 'phosphosite_plot_png')
    figure = replace_once(figure, 'def phosphosite_plot_png(', 'def render_plot(data, ')
    figure = replace_once(figure, '    summary = phosphosite_plot_table()', '    summary = prepare_table(data)')
    figure = figure.replace('plt, _ = _get_plt()', 'plt = get_plt()')
    figure = figure.replace('_cm_to_inch(', 'cm_to_inch(').replace('_to_png_bytes(', 'to_png_bytes(')
    return extract_notebook_source(merge_source('import numpy as np\nimport pandas as pd', table, figure,
        extract_notebook_source(qc_source('boxplot').code, ('get_plt', 'cm_to_inch', 'to_png_bytes', 'apply_advanced_axes')).code,
        extract_notebook_source(module_source('plot_styling.py'), ('advanced_color',)).code), ('prepare_table', 'render_plot'))


@lru_cache(maxsize=1)
def count_module():
    module = ModuleType('_copylot_portable_phospho_counts')
    sys.modules[module.__name__] = module
    exec(count_source().code, module.__dict__)
    return module


def render_counts(**options):
    return _render('counts', **options)


@lru_cache(maxsize=1)
def coverage_source():
    original = module_source('phospho_tools.py')
    counts = function_definition(original, '_coverage_counts')
    counts = replace_once(counts, 'def _coverage_counts(', 'def _coverage_counts(data, metadata, is_log2, ')
    counts = replace_once(counts, '    frame, meta, _ = _phospho_context()', '    frame, meta = data, metadata')
    counts = replace_once(counts, '    annotation = get_annotation("phospho")\n    if not bool(getattr(annotation, "is_log2_transformed", False)):',
                           '    if not is_log2:')
    table = function_definition(original, 'phospho_coverage_table').replace(
        'def phospho_coverage_table(', 'def prepare_table(data, metadata, is_log2, ')
    figure = function_definition(original, 'phospho_coverage_png').replace(
        'def phospho_coverage_png(', 'def render_plot(data, metadata, is_log2, ')
    code = '\n\n'.join((counts, table, figure, function_definition(original, '_filter_meta_conditions')))
    code = code.replace('_coverage_counts(include_id=', '_coverage_counts(data, metadata, is_log2, include_id=')
    code = code.replace('plt, _ = _get_plt()', 'plt = get_plt()').replace('_extract_id_or_number(', 'extract_sample_id(')
    code = code.replace('_cm_to_inch(', 'cm_to_inch(').replace('_to_png_bytes(', 'to_png_bytes(')
    return extract_notebook_source(merge_source('import numpy as np\nimport pandas as pd', code,
        extract_notebook_source(count_source().code, ('get_plt', 'cm_to_inch', 'to_png_bytes', 'apply_advanced_axes', 'advanced_color')).code,
        extract_notebook_source(module_source('functions.py'), ('extract_sample_id',)).code,
        extract_notebook_source(module_source('plot_styling.py'), ('advanced_label',)).code), ('prepare_table', 'render_plot'))


@lru_cache(maxsize=1)
def coverage_module():
    module = ModuleType('_copylot_portable_phospho_coverage')
    sys.modules[module.__name__] = module
    exec(coverage_source().code, module.__dict__)
    return module


def render_coverage(**options):
    return _render('coverage', **options)


@lru_cache(maxsize=2)
def category_source(plot):
    if plot not in {'distribution', 'sty'}:
        raise ValueError('Unsupported phospho notebook.')
    original = module_source('phospho_tools.py')
    table = function_definition(original, f'phospho_{plot}_table')
    table = table.replace(f'def phospho_{plot}_table(', 'def prepare_table(data, ')
    table = replace_once(table, '    frame, _, _ = _phospho_context()', '    frame = data')
    figure = function_definition(original, f'phospho_{plot}_png')
    figure = figure.replace(f'def phospho_{plot}_png(', 'def render_plot(data, ')
    figure = figure.replace(f'phospho_{plot}_table(', 'prepare_table(data, ')
    figure = figure.replace('plt, _ = _get_plt()', 'plt = get_plt()')
    figure = figure.replace('plt, mtick = _get_plt()', 'plt = get_plt()\n    import matplotlib.ticker as mtick')
    figure = figure.replace('_cm_to_inch(', 'cm_to_inch(').replace('_to_png_bytes(', 'to_png_bytes(')
    return extract_notebook_source(merge_source('import numpy as np\nimport pandas as pd', table, figure,
        extract_notebook_source(count_source().code, ('get_plt', 'cm_to_inch', 'to_png_bytes',
            'apply_advanced_axes', 'advanced_color')).code), ('prepare_table', 'render_plot'))


@lru_cache(maxsize=2)
def category_module(plot):
    module = ModuleType(f'_copylot_portable_phospho_{plot}')
    sys.modules[module.__name__] = module
    exec(category_source(plot).code, module.__dict__)
    return module


def render_distribution(**options):
    return _render('distribution', **options)


def render_sty(**options):
    return _render('sty', **options)


def _render(plot, **options):
    from app.services import phospho_tools
    from app.services.dataset_store import get_current_dataset
    from app.services.annotation_store import get_annotation
    from app.services.phospho_localization import get_localization_cutoff
    from app.services.plot_export import plot_output_format
    from app.services.runtime_cache import runtime_cache_version
    from app.services.session_context import get_session_id

    revision = runtime_cache_version()
    renderer = phospho_tools.phosphosite_plot_png if plot == 'counts' else getattr(phospho_tools, f'phospho_{plot}_png')
    bound = inspect.signature(renderer).bind(**options)
    bound.apply_defaults()
    settings = dict(bound.arguments)
    frame, metadata, samples = phospho_tools._phospho_context()
    metadata = metadata[['sample', 'condition']].copy(deep=True)
    cutoff = get_localization_cutoff()
    dataset = get_current_dataset('phospho')
    required = {'counts': ('Protein_group', 'Phosphoprotein', 'UPD_seq', 'PTM_Collapse_key'),
        'coverage': (*samples, 'PTM_localization'),
        'distribution': ('site_num', 'Phosphoprotein', 'Protein_group', 'PTM_Collapse_key'),
        'sty': ('PTM_Collapse_key',)}[plot]
    columns = [c for c in required if c in frame]
    data = frame[columns].copy(deep=True)
    source = count_source() if plot == 'counts' else coverage_source() if plot == 'coverage' else category_source(plot)
    module = count_module() if plot == 'counts' else coverage_module() if plot == 'coverage' else category_module(plot)
    preparation = {}
    if plot == 'coverage':
        settings['is_log2'] = bool(getattr(get_annotation('phospho'), 'is_log2_transformed', False))
        preparation = {key: settings[key] for key in ('include_id', 'conditions', 'mode', 'is_log2')}
    elif plot == 'distribution':
        preparation = {'cutoff': settings['cutoff']}
    table = module.prepare_table(data, metadata, **preparation) if plot == 'coverage' else module.prepare_table(data, **preparation)
    fmt = plot_output_format.get()
    context = module.plot_output_format.set(fmt)
    try:
        image = module.render_plot(data, metadata, **settings) if plot == 'coverage' else module.render_plot(data, **settings)
    finally:
        module.plot_output_format.reset(context)
    explanation = {
        'distribution': 'Captured original-source rows after the session localization cutoff. Existing site_num '
            'values take precedence; otherwise distinct site keys are counted per protein group. The notebook '
            'repeats the upper-tail quantile trimming, frequency calculation and original renderer.',
        'sty': 'Captured original-source site-key rows after the session localization cutoff. The notebook '
            'repeats S/T/Y parsing, retains Unparsed rows in the total, and reproduces row counts, rounded '
            'percentages and the secondary percentage axis. Duplicate rows retain the original counting semantics.',
    }.get(plot)
    recipe = NotebookRecipe(plot_name=f'Phosphosite {"STY" if plot == "sty" else plot.title()}',
        source=source, settings=settings,
        original_filename=dataset.filename, resources={'input.parquet': dataframe_bytes(data),
            'metadata.parquet': dataframe_bytes(metadata[['sample', 'condition']]),
            'table.parquet': dataframe_bytes(table), f'original.{fmt}': bytes(image)},
        provenance={'kind': 'phospho', 'plot': f'phosphosite_{plot}', 'sourceUsed': 'original_source_rows',
                    'localizationCutoff': cutoff},
        input_explanation=explanation or ('Captured original-source identifier rows after the session localization cutoff. '
            'Counts are distinct protein groups, cleaned peptide sequences and site keys, not intensity detection counts. '
            'The exact source column fallback and count ordering are repeated. Normalization, missingness filtering '
            'and imputation are not used by this plot. The cutoff is recorded; its already-selected rows are bundled.'
            if plot == 'counts' else 'Captured original-source intensities and localization probabilities after the session cutoff. '
            'Zero is missing on the linear scale and observed on the log2 scale; nonfinite values are missing. '
            'The notebook repeats Class I (probability >= 0.75), Not Class I and Unclassified counts, '
            'condition means/sample SDs, sample labels and seeded jitter. Normalization, missingness filtering '
            'and imputation are not applied. The original declared scale and cutoff are recorded.'),
        calculation="from IPython.display import Image, display\n"
            f"preparation = {{key: settings[key] for key in {tuple(preparation)!r}}}\n"
            + ("table = functions.prepare_table(data, metadata, **preparation)\n" if plot == 'coverage' else
               "table = functions.prepare_table(data, **preparation)\n") +
            "pd.testing.assert_frame_equal(table, read_resource_table(RESOURCES / 'table.parquet'), check_exact=True)\n"
            "table.to_csv('reproduced_counts.csv', index=False)\ndisplay(table)\n"
            + ("image = functions.render_plot(data, metadata, **settings)\n" if plot == 'coverage' else
               "image = functions.render_plot(data, **settings)\n") +
            "Path('reproduced.png').write_bytes(image)\ndisplay(Image(data=image))")
    try:
        token = capture_notebook(get_session_id(), recipe) if runtime_cache_version() == revision else ''
    except ValueError:
        token = ''
    return image, token
