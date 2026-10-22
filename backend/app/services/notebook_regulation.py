"""Portable phosphoprotein regulation, from site statistics to plot and table."""
from functools import lru_cache
import inspect
import sys
from types import ModuleType

from app.services.notebook_archive import NotebookRecipe, dataframe_bytes
from app.services.notebook_preprocessing import capture_notebook
from app.services.notebook_source import extract_notebook_source, function_definition, merge_source, module_source
from app.services.notebook_volcano import (
    PROTEIN_CORRECTION_EXPLANATION, frozen_protein_comparison, protein_stats_code, volcano_source)


@lru_cache(maxsize=2)
def regulation_source(interactive=False):
    original = module_source('phospho_tools.py')
    table = function_definition(original, 'phosprot_regulation_table')
    start = table.index('    from app.services.stats_tools import _volcano_dataframe')
    end = table.index('    required =', start)
    table = table[:start] + table[end:]
    table = table.replace('def phosprot_regulation_table(\n    *,', 'def prepare_table(volcano_df, *,')
    name = 'phosprot_regulation_html' if interactive else 'phosprot_regulation_png'
    figure = function_definition(original, name).replace(f'def {name}(\n    *,', 'def render_plot(table, *,')
    start = figure.index('    table = phosprot_regulation_table(')
    end = figure.index('\n    )', start) + len('\n    )')
    figure = figure[:start] + figure[end:]
    helpers = '\n\n'.join(function_definition(original, n) for n in (
        '_empty_phosprot_regulation_html', '_phosprot_regulation_figure')) if interactive else ''
    code = '\n\n'.join((table, figure, helpers))
    for before, after in (('plt, _ = _get_plt()', 'plt = get_plt()'),
            ('_cm_to_inch(', 'cm_to_inch('), ('_to_png_bytes(', 'to_png_bytes('),
            ('_get_plotly()', 'get_plotly_px()'), ('_get_plotly_go()', 'get_plotly_go()'),
            ('_plotly_html(', 'plotly_html(')):
        code = code.replace(before, after)
    common = module_source('plotting_common.py')
    styling = '\n'.join(line for line in module_source('plot_styling.py').splitlines() if not line.startswith('from app.'))
    styling += '\n\n' + function_definition(common, 'get_plt') + '\n\ndef _get_plt():\n    return get_plt()\n'
    styles = extract_notebook_source(styling, ('marker_style', 'plotly_marker', 'get_plt', 'apply_advanced_axes')).code
    return extract_notebook_source(merge_source(volcano_source(True).code, styles,
        extract_notebook_source(module_source('plot_export.py'), ('to_png_bytes', 'cm_to_inch')).code,
        function_definition(common, 'get_plotly_px'), code,
        'PHOSPROT_REGULATION_EMPTY_MESSAGE = "No phosphosites pass the selected significance and fold-change thresholds"'),
        ('calculate_table', 'prepare_table', 'render_plot'))


@lru_cache(maxsize=2)
def regulation_module(interactive=False):
    module = ModuleType(f'_copylot_portable_regulation_{interactive}')
    sys.modules[module.__name__] = module
    exec(regulation_source(interactive).code, module.__dict__)
    return module


def render_regulation(*, interactive=False, **options):
    from app.services import phospho_tools, stats_tools
    from app.services.annotation_store import get_annotation
    from app.services.dataset_store import get_current_dataset
    from app.services.notebook_provenance import input_history, NotebookProvenanceError
    from app.services.phospho_localization import get_localization_cutoff
    from app.services.plot_export import plot_output_format
    from app.services.runtime_cache import runtime_cache_version
    from app.services.session_context import get_session_id

    revision = runtime_cache_version()
    renderer = phospho_tools.phosprot_regulation_html if interactive else phospho_tools.phosprot_regulation_png
    bound = inspect.signature(renderer).bind(**options)
    bound.apply_defaults()
    settings = dict(bound.arguments)
    data, metadata, _ = phospho_tools._phospho_regulation_context(settings['data_source'])
    metadata = metadata[[c for c in ('sample', 'condition', 'pair_id') if c in metadata]].copy(deep=True)
    source = settings['data_source']
    mask = stats_tools._imputation_mask('phospho', source, data, metadata['sample'].astype(str).tolist())
    identifiers = ['GeneNames', 'Gene_group', 'ProteinNames', 'PTM_Collapse_key', 'UPD_seq',
                   'Protein_group', 'Phosphoprotein', 'site_num', 'PTM_Collapse_keys']
    data = data[[c for c in dict.fromkeys([*metadata['sample'].tolist(), *identifiers]) if c in data]].copy(deep=True)
    annotation, dataset = get_annotation('phospho'), get_current_dataset('phospho')
    if annotation is None:
        raise NotebookProvenanceError('Generate annotations before exporting a regulation notebook.')
    _, imputation, uses_imputed, documentation = input_history('phospho', annotation, dataset, source)
    calculation = {k: settings[k] for k in ('condition1', 'condition2', 'p_value_threshold',
        'log2fc_threshold', 'test_type', 'use_uncorrected', 'data_source', 'protein_correction')}
    calculation.update(kind='phospho', identifier='workflow')
    preparation = {k: settings[k] for k in inspect.signature(phospho_tools.phosprot_regulation_table).parameters
                   if k != 'protein_correction'}
    module = regulation_module(interactive)
    protein_resources, protein_calculation, protein_stats = frozen_protein_comparison(
        'phospho', settings.get('protein_correction'), calculation, source, module, identifiers)
    _, _, statistics, _ = module.calculate_table(data, metadata, mask, protein_stats=protein_stats, **calculation)
    table = module.prepare_table(statistics, **preparation)
    fmt = 'html' if interactive else plot_output_format.get()
    if interactive:
        content = module.render_plot(table, **settings)
    else:
        context = module.plot_output_format.set(fmt)
        try:
            content = module.render_plot(table, **settings)
        finally:
            module.plot_output_format.reset(context)
    resources = {'input.parquet': dataframe_bytes(data), 'metadata.parquet': dataframe_bytes(metadata),
        'table.parquet': dataframe_bytes(table), f'original.{fmt}': content.encode() if interactive else bytes(content),
        **protein_resources}
    if mask is not None:
        resources['imputation_mask.parquet'] = dataframe_bytes(mask)
    recipe = NotebookRecipe(plot_name='Phosphoprotein Regulation', source=regulation_source(interactive),
        settings={**settings, **({'protein_calculation': protein_calculation} if protein_stats is not None else {})},
        original_filename=dataset.filename, resources=resources,
        uses_imputed_input=uses_imputed, imputation_recipe=documentation,
        provenance={'kind': 'phospho', 'plot': 'phosprot_regulation', 'sourceUsed': source,
            'localizationCutoff': get_localization_cutoff(), 'filter': annotation.filter_config.model_dump(),
            'imputation': imputation.model_dump() if imputation else None},
        input_explanation='Captured processed phosphosite intensities and pairing metadata. The notebook repeats '
            'site-level testing and significance classification, then sums significant site fold changes by protein. '
            'Imputed values are frozen; original-upload preprocessing is documented, not rerun.'
            + (PROTEIN_CORRECTION_EXPLANATION if protein_stats is not None else ''),
        calculation="mask_path = RESOURCES / 'imputation_mask.parquet'\n"
            "mask = read_resource_table(mask_path) if mask_path.exists() else None\n"
            f"calculation = {{key: settings[key] for key in {tuple(k for k in calculation if k not in {'kind', 'identifier'})!r}}}\n"
            + protein_stats_code("settings.get('protein_correction')") +
            "_, _, statistics, _ = functions.calculate_table(data, metadata, mask, kind='phospho', identifier='workflow', protein_stats=protein_stats, **calculation)\n"
            f"preparation = {{key: settings[key] for key in {tuple(preparation)!r}}}\n"
            "table = functions.prepare_table(statistics, **preparation)\n"
            "pd.testing.assert_frame_equal(table, read_resource_table(RESOURCES / 'table.parquet'), check_exact=True)\n"
            "table.to_csv('phosphoprotein_regulation.csv', index=False)\n"
            "from IPython.display import display, HTML, Image\ndisplay(table)\n"
            "output = functions.render_plot(table, **{k: v for k, v in settings.items() if k != 'protein_calculation'})\n" +
            ("Path('reproduced.html').write_bytes(output.encode('utf-8'))\ndisplay(HTML(output))" if interactive else
             "Path('reproduced.png').write_bytes(output)\ndisplay(Image(data=output))"))
    try:
        token = capture_notebook(get_session_id(), recipe) if runtime_cache_version() == revision else ''
    except ValueError:
        token = ''
    return content, token
