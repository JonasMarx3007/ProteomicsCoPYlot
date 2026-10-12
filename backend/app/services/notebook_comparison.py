"""Comparison notebooks using the same QC matrix, calculations and renderers."""
from functools import lru_cache
import inspect
import json
import sys
from types import ModuleType

from app.services.notebook_archive import NotebookRecipe, dataframe_bytes
from app.services.notebook_preprocessing import capture_notebook
from app.services.notebook_source import extract_notebook_source, function_definition, merge_source, module_source, replace_once
from app.services.notebook_volcano import volcano_source


@lru_cache(maxsize=3)
def comparison_source(plot, interactive=False):
    if plot not in {'pearson', 'venn'} or (plot == 'venn' and interactive):
        raise ValueError('Unsupported comparison notebook.')
    original = module_source('comparison_tools.py')
    prefix = 'pearson_correlation' if plot == 'pearson' else 'venn'
    renderer = prefix + ('_html' if interactive else '_png')
    names = [prefix + '_table', renderer, '_rename_if_condition', '_wrap_label', '_id_column']
    names += (['_pearson_vectors', '_pearson_vectors_with_features', '_legacy_area_as_diameter']
              if plot == 'pearson' else ['_venn_sets', '_feature_set_from_sample', '_feature_set_from_condition', '_get_venn'])
    definitions = []
    for name in names:
        code = function_definition(original, name)
        if name in {prefix + '_table', renderer, '_pearson_vectors', '_pearson_vectors_with_features', '_venn_sets'}:
            code = replace_once(code, f'def {name}(\n', f'def {name}(data, metadata,\n')
        code = code.replace('    frame, meta, _ = _analysis_context(kind)', '    frame, meta = data, metadata')
        for helper in ('_pearson_vectors', '_pearson_vectors_with_features', '_venn_sets'):
            code = code.replace(f'{helper}(\n        kind=kind,', f'{helper}(\n        data, metadata, kind=kind,')
        definitions.append(code)
    code = '\n\n'.join(definitions).replace('AnnotationKind', 'str')
    for before, after in (('_get_plt()', 'get_plt()'), ('_get_plotly()', 'get_plotly_go()'),
            ('_plotly_html(', 'plotly_html('), ('_truncate_hover_text(', 'truncate_hover_text('),
            ('_cm_to_inch(', 'cm_to_inch('), ('_cm_to_px(', 'cm_to_px('), ('_to_png_bytes(', 'to_png_bytes(')):
        code = code.replace(before, after)
    code = code.replace(prefix + '_table(', 'prepare_table(').replace(renderer + '(', 'render_plot(')
    common = module_source('plotting_common.py')
    styling = '\n'.join(line for line in module_source('plot_styling.py').splitlines() if not line.startswith('from app.'))
    styling += '\n\n' + function_definition(common, 'get_plt') + '\n\ndef _get_plt():\n    return get_plt()\n'
    return extract_notebook_source(merge_source(
        'import numpy as np\nimport pandas as pd\nfrom textwrap import fill', code,
        extract_notebook_source(styling, ('get_plt', 'apply_advanced_axes', 'advanced_plotly_layout',
            'advanced_color', 'advanced_label', 'marker_style', 'plotly_marker', 'resolve_reference_line')).code,
        extract_notebook_source(module_source('functions.py'), ('condition_mean',)).code,
        extract_notebook_source(module_source('plot_export.py'), ('to_png_bytes', 'cm_to_inch', 'cm_to_px')).code,
        extract_notebook_source(volcano_source(True).code, ('plotly_html', 'get_plotly_go')).code,
        function_definition(common, 'truncate_hover_text')),
        ('prepare_table', 'render_plot'))


@lru_cache(maxsize=3)
def comparison_module(plot, interactive=False):
    module = ModuleType(f'_copylot_portable_comparison_{plot}_{interactive}')
    sys.modules[module.__name__] = module
    exec(comparison_source(plot, interactive).code, module.__dict__)
    return module


def render_comparison(plot, *, interactive=False, **options):
    from app.services import comparison_tools
    from app.services.annotation_store import get_annotation
    from app.services.dataset_store import get_current_dataset
    from app.services.notebook_provenance import input_history
    from app.services.phospho_localization import get_localization_cutoff
    from app.services.plot_export import plot_output_format
    from app.services.runtime_cache import runtime_cache_version
    from app.services.session_context import get_session_id

    revision = runtime_cache_version()
    source = comparison_source(plot, interactive)
    prefix = 'pearson_correlation' if plot == 'pearson' else 'venn'
    renderer = getattr(comparison_tools, prefix + ('_html' if interactive else '_png'))
    bound = inspect.signature(renderer).bind(**options)
    bound.apply_defaults()
    settings = dict(bound.arguments)
    kind = settings['kind']
    data, metadata, samples = comparison_tools._analysis_context(kind)
    identifiers = [comparison_tools._id_column(kind, data)] if plot == 'venn' or interactive else []
    data = data[list(dict.fromkeys([*samples, *identifiers]))].copy(deep=True)
    metadata = metadata[['sample', 'condition']].copy(deep=True)
    annotation, dataset = get_annotation(kind), get_current_dataset(kind)
    lineage, imputation, uses_imputed, documentation = input_history(kind, annotation, dataset)
    preparation = {key: settings[key] for key in inspect.signature(getattr(comparison_tools, prefix + '_table')).parameters
                   if key in settings}
    module = comparison_module(plot, interactive)
    table = module.prepare_table(data, metadata, **preparation)
    fmt = 'html' if interactive else plot_output_format.get()
    if interactive:
        content = module.render_plot(data, metadata, **settings)
    else:
        context = module.plot_output_format.set(fmt)
        try:
            content = module.render_plot(data, metadata, **settings)
        finally:
            module.plot_output_format.reset(context)
    # Pearson's summary intentionally mixes labels, an integer and a float.
    # JSON preserves those scalar types without coercing the column to strings.
    resources = {'input.parquet': dataframe_bytes(data), 'metadata.parquet': dataframe_bytes(metadata),
        'table.json': json.dumps(table.to_dict(orient='records'), allow_nan=False).encode(),
        f'original.{fmt}': content.encode() if interactive else bytes(content)}
    recipe = NotebookRecipe(plot_name='Comparison ' + ('Pearson' if plot == 'pearson' else 'Venn'),
        source=source, settings=settings, resources=resources, original_filename=dataset.filename,
        uses_imputed_input=uses_imputed, imputation_recipe=documentation,
        provenance={'kind': kind, 'plot': 'comparison_' + plot, 'sourceUsed': 'data',
            'localizationCutoff': get_localization_cutoff(),
            'upstreamCollapse': lineage.model_dump() if lineage else None,
            'imputation': imputation.model_dump() if imputation else None},
        input_explanation='Captured QC matrix before downstream missingness filtering and imputation. '
            'The notebook repeats sample selection or condition aggregation and the original rendering. '
            'Pearson uses overlapping observations; condition means require at least one observed sample. '
            'Venn counts distinct identifiers detected in each sample, or in at least min_present samples of each condition. '
            'Already-applied preprocessing and any upstream phosphoprotein collapse are not rerun.',
        calculation=f"preparation = {{key: settings[key] for key in {tuple(preparation)!r}}}\n"
            "table = functions.prepare_table(data, metadata, **preparation)\n"
            "expected = pd.DataFrame(json.loads((RESOURCES / 'table.json').read_text(encoding='utf-8')))\n"
            "pd.testing.assert_frame_equal(table, expected, check_exact=True)\n"
            "table.to_csv('comparison_summary.csv', index=False)\n"
            "from IPython.display import display, HTML, Image\ndisplay(table)\n"
            "output = functions.render_plot(data, metadata, **settings)\n" +
            ("Path('reproduced.html').write_bytes(output.encode('utf-8'))\ndisplay(HTML(output))" if interactive else
             "Path('reproduced.png').write_bytes(output)\ndisplay(Image(data=output))"))
    try:
        token = capture_notebook(get_session_id(), recipe) if runtime_cache_version() == revision else ''
    except ValueError:
        token = ''
    return content, token
