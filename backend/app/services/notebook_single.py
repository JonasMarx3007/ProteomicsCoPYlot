"""Single-feature plots and paired tables replayed from captured analysis inputs."""
from functools import lru_cache
import inspect
import sys
from types import ModuleType

from app.services.notebook_archive import NotebookRecipe, dataframe_bytes
from app.services.notebook_preprocessing import capture_notebook
from app.services.notebook_qc import _source, _definition, _replace_once, _merge_source, qc_source
from app.services.notebook_source import extract_notebook_source


@lru_cache(maxsize=1)
def box_source():
    original = _source('single_protein_tools.py')
    prepare = _definition(original, '_boxplot_data')
    prepare = _replace_once(prepare, 'def _boxplot_data(', 'def prepare_table(data, metadata, ')
    prepare = _replace_once(prepare, '    frame, sample_columns, meta = _analysis_frame(kind, data_source=data_source)',
        '    frame, meta = data, metadata\n    sample_columns = [s for s in meta["sample"].astype(str) if s in frame.columns]')
    figure = _definition(original, 'single_protein_boxplot_plot')
    figure = _replace_once(figure, 'def single_protein_boxplot_plot(',
        'def render_plot(data, metadata, condition_colors, centered, ')
    figure = _replace_once(figure, '_boxplot_data(\n        kind,', 'prepare_table(data, metadata,\n        kind,')
    figure = _replace_once(figure, 'advanced_condition_colors(kind, plt, list(labels), advanced)', 'condition_colors')
    figure = figure.replace('_phosprot_values_are_centred(kind)', 'centered')
    code = original.replace(_definition(original, '_boxplot_data'), prepare)
    code = code.replace(_definition(original, 'single_protein_boxplot_plot'), figure)
    code = code.replace('AnnotationKind', 'str').replace('_extract_id_or_number(', 'extract_sample_id(')
    code = code.replace('_get_plt()', 'get_plt()').replace('_cm_to_inch(', 'cm_to_inch(').replace('_to_png_bytes(', 'to_png_bytes(')
    # Keep only the local definitions first; imported stateful application helpers
    # are replaced by their pure dependency closures below.
    names = ('_normalize_identifier', '_line_box_key_column_for_identifier', '_build_sample_labels',
             '_feature_label', '_feature_match_mask', '_select_conditions', 'prepare_table', 'render_plot')
    # One `_gene_tokens` for the app, kept in stats_tools.py (2026-10-02).
    local = '\n\n'.join([_definition(_source('stats_tools.py'), '_gene_tokens'),
                         *(_definition(code, name) for name in names)])
    local = local.replace('SingleProteinIdentifier', 'str')
    styling = '\n'.join(line for line in _source('plot_styling.py').splitlines() if not line.startswith('from app.'))
    return extract_notebook_source(_merge_source('import numpy as np\nimport pandas as pd', local,
        extract_notebook_source(_source('functions.py'), ('condition_sample_labels', 'extract_sample_id', 'intensity_unit_label')).code,
        extract_notebook_source(styling, ('resolve_marker', 'advanced_number', 'advanced_text', 'advanced_label', 'apply_advanced_axes')).code,
        extract_notebook_source(qc_source('boxplot').code, ('get_plt', 'cm_to_inch', 'to_png_bytes')).code),
        ('prepare_table', 'render_plot'))


@lru_cache(maxsize=1)
def box_module():
    module = ModuleType('_copylot_portable_single_box')
    sys.modules[module.__name__] = module
    exec(box_source().code, module.__dict__)
    return module


@lru_cache(maxsize=1)
def line_source():
    original = _source('single_protein_tools.py')
    long_table = _definition(original, '_lineplot_long_table')
    long_table = _replace_once(long_table, 'def _lineplot_long_table(', 'def _lineplot_long_table(data, metadata, ')
    long_table = _replace_once(long_table, '    frame, sample_columns, meta = _analysis_frame(kind, data_source=data_source)',
        '    frame, meta = data, metadata\n    sample_columns = [s for s in meta["sample"].astype(str) if s in frame.columns]')
    table = _definition(original, 'single_protein_lineplot_table')
    table = _replace_once(table, 'def single_protein_lineplot_table(', 'def prepare_table(data, metadata, ')
    figure = _definition(original, 'single_protein_lineplot_plot')
    figure = _replace_once(figure, 'def single_protein_lineplot_plot(', 'def render_plot(data, metadata, centered, ')
    code = '\n\n'.join((long_table, table, figure))
    code = code.replace('_lineplot_long_table(\n        kind,', '_lineplot_long_table(data, metadata,\n        kind,')
    code = code.replace('AnnotationKind', 'str').replace('_phosprot_values_are_centred(kind)', 'centered')
    code = code.replace('_get_plt()', 'get_plt()').replace('_cm_to_inch(', 'cm_to_inch(').replace('_to_png_bytes(', 'to_png_bytes(')
    helpers = extract_notebook_source(box_source().code, ('_normalize_identifier',
        '_line_box_key_column_for_identifier', '_build_sample_labels', '_feature_label',
        '_feature_match_mask', '_gene_tokens', '_select_conditions', 'intensity_unit_label',
        'apply_advanced_axes', 'get_plt', 'cm_to_inch', 'to_png_bytes'))
    return extract_notebook_source(_merge_source('import numpy as np\nimport pandas as pd', helpers.code, code),
                                   ('prepare_table', 'render_plot'))


@lru_cache(maxsize=1)
def line_module():
    module = ModuleType('_copylot_portable_single_line')
    sys.modules[module.__name__] = module
    exec(line_source().code, module.__dict__)
    return module


@lru_cache(maxsize=1)
def heatmap_source():
    original = _source('single_protein_tools.py')
    matrix = _definition(original, '_heatmap_matrix')
    matrix = _replace_once(matrix, 'def _heatmap_matrix(', 'def _heatmap_matrix(data, metadata, ')
    matrix = _replace_once(matrix, '    frame, _, meta = _analysis_frame(kind, data_source=data_source)',
                           '    frame, meta = data, metadata')
    table = _definition(original, 'single_protein_heatmap_table').replace(
        'def single_protein_heatmap_table(', 'def prepare_table(data, metadata, ')
    figure = _definition(original, 'single_protein_heatmap_plot').replace(
        'def single_protein_heatmap_plot(', 'def render_plot(data, metadata, ')
    local = '\n\n'.join(_definition(original, name) for name in (
        '_site_label', '_heatmap_protein_group_column', '_heatmap_key_column_for_identifier'))
    code = '\n\n'.join((local, matrix, table, figure))
    code = code.replace('_heatmap_matrix(\n        kind=', '_heatmap_matrix(data, metadata,\n        kind=')
    code = code.replace('_phosprot_values_are_centred(kind)', 'False')  # Phosphosite-only renderer.
    code = code.replace('AnnotationKind', 'str').replace('SingleProteinIdentifier', 'str')
    code = code.replace('_get_plt()', 'get_plt()').replace('_get_seaborn()', 'get_sns()')
    code = code.replace('_cm_to_inch(', 'cm_to_inch(').replace('_to_png_bytes(', 'to_png_bytes(')
    helpers = extract_notebook_source(box_source().code, ('_normalize_identifier', '_build_sample_labels',
        '_feature_match_mask', '_select_conditions', 'intensity_unit_label', 'apply_advanced_axes',
        'get_plt', 'cm_to_inch', 'to_png_bytes'))
    return extract_notebook_source(_merge_source('import numpy as np\nimport pandas as pd', helpers.code, code,
        extract_notebook_source(_source('plotting_common.py'), ('get_sns',)).code,
        extract_notebook_source(_source('plot_styling.py'), ('advanced_color_map',)).code,
        extract_notebook_source(_source('clustering_tools.py'), ('row_zscore', 'drop_incomplete_features', 'heatmap_notice')).code),
        ('prepare_table', 'render_plot'))


@lru_cache(maxsize=1)
def heatmap_module():
    module = ModuleType('_copylot_portable_single_heatmap')
    sys.modules[module.__name__] = module
    exec(heatmap_source().code, module.__dict__)
    return module


def render_heatmap(**options):
    return _render('heatmap', **options)


def render_box(**options):
    return _render('boxplot', **options)


def render_line(**options):
    return _render('lineplot', **options)


def _render(plot, **options):
    from app.services import single_protein_tools as single
    from app.services.annotation_store import get_annotation
    from app.services.dataset_store import get_current_dataset
    from app.services.functions import _phosprot_values_are_centred
    from app.services.notebook_provenance import input_history
    from app.services.plot_styling import advanced_condition_colors
    from app.services.plot_export import plot_output_format
    from app.services.runtime_cache import runtime_cache_version
    from app.services.session_context import get_session_id

    revision = runtime_cache_version()
    renderer = getattr(single, f'single_protein_{plot}_plot')
    bound = inspect.signature(renderer).bind(**options)
    bound.apply_defaults()
    settings = dict(bound.arguments)
    kind = settings['kind']
    annotation, dataset = get_annotation(kind), get_current_dataset(kind)
    lineage, imputation, uses_imputed, documentation = input_history(kind, annotation, dataset, source=settings['data_source'])
    frame, samples, metadata = single._analysis_frame(kind, settings['data_source'])
    key = (single._heatmap_key_column_for_identifier(frame, settings['identifier']) if plot == 'heatmap'
           else single._line_box_key_column_for_identifier(kind, frame, settings['identifier']))
    try:
        workflow = single._line_box_key_column_for_identifier(kind, frame, 'workflow')
    except ValueError:
        workflow = key
    features = settings['proteins'] if plot == 'lineplot' else [settings['protein']]
    selected = single._feature_match_mask(frame[key], {str(value).strip() for value in features if str(value).strip()}, kind,
                                           single._normalize_identifier(settings['identifier']))
    data = frame.loc[selected, list(dict.fromkeys([key, workflow, *samples]))].copy(deep=True)
    metadata = metadata[['sample', 'condition']].copy(deep=True)
    keys = ('kind', 'conditions', 'identifier', 'data_source') + {
        'boxplot': ('protein',), 'lineplot': ('proteins', 'include_id'),
        'heatmap': ('protein', 'include_id', 'filter_m1', 'cluster_rows', 'cluster_cols', 'value_type'),
    }[plot]
    preparation = {k: settings[k] for k in keys}
    module = {'boxplot': box_module, 'lineplot': line_module, 'heatmap': heatmap_module}[plot]()
    if plot == 'boxplot':
        _, labels, _, table = module.prepare_table(data, metadata, **preparation)
        settings['condition_colors'] = advanced_condition_colors(kind, module.get_plt(), labels, settings['advanced'])
    else:
        table = module.prepare_table(data, metadata, **preparation)
    if plot != 'heatmap':
        settings['centered'] = _phosprot_values_are_centred(kind)
    fmt = plot_output_format.get()
    format_token = module.plot_output_format.set(fmt)
    try:
        image = module.render_plot(data, metadata, **settings)
    finally:
        module.plot_output_format.reset(format_token)
    details = {
        'boxplot': 'Per-sample median consolidation, finite-value exclusion, summary statistics, '
                   'small-sample points and seeded jitter are repeated. Project colors are frozen. ',
        'lineplot': 'Per-sample median consolidation, missing sample positions, sample order, labels, '
                    'connections between measured points and optional marker-free NA baseline vertices, '
                    'feature colors and the rounded table are repeated from full-precision values. ',
        'heatmap': 'Site keys, M1 selection, log2 values or row z-scores, complete-feature clustering, '
                   'exclusion notices and the rounded table are repeated from full-precision values. ',
    }[plot]
    recipe = NotebookRecipe(plot_name=f'Single Protein {plot.title()}',
        source={'boxplot': box_source, 'lineplot': line_source, 'heatmap': heatmap_source}[plot](), settings=settings,
        original_filename=dataset.filename, uses_imputed_input=uses_imputed, imputation_recipe=documentation,
        resources={'input.parquet': dataframe_bytes(data), 'metadata.parquet': dataframe_bytes(metadata),
            'table.parquet': dataframe_bytes(table), f'original.{fmt}': bytes(image)},
        provenance={'kind': kind, 'plot': f'single_{plot}', 'sourceUsed': settings['data_source'],
            'plotNotice': getattr(image, 'notice', ''),
            'normalization': annotation.filter_config.normalization, 'filter': annotation.filter_config.model_dump(),
            'upstreamCollapse': lineage.model_dump() if lineage else None,
            'imputation': imputation.model_dump() if imputation else None},
        input_explanation='The exact selected feature rows are captured from the chosen processed log2 matrix. '
            'The notebook repeats feature/gene matching, the paired table and the original renderer. ' + details +
            'Advanced options are frozen. Imputed values are never redrawn; '
            'upstream processing and collapse are documented, not rerun.',
        calculation="from IPython.display import Image, display\n"
            f"preparation = {{k: settings[k] for k in {keys!r}}}\n"
            + ("_, _, _, table = functions.prepare_table(data, metadata, **preparation)\n" if plot == 'boxplot'
               else "table = functions.prepare_table(data, metadata, **preparation)\n") +
            "pd.testing.assert_frame_equal(table, pd.read_parquet(RESOURCES / 'table.parquet'), check_exact=True)\n"
            "table.to_csv('reproduced_summary.csv', index=False)\ndisplay(table)\n"
            "image = functions.render_plot(data, metadata, **settings)\n"
            "if getattr(image, 'notice', ''): print(image.notice)\n"
            "Path('reproduced.png').write_bytes(image)\ndisplay(Image(data=image))")
    try:
        token = capture_notebook(get_session_id(), recipe) if runtime_cache_version() == revision else ''
    except ValueError:
        token = ''
    return image, token
