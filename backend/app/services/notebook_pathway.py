"""Pathway heatmaps replayed from captured matrices and GO membership."""
from functools import lru_cache
import inspect
import sys
from types import ModuleType

from app.services.notebook_archive import NotebookRecipe, dataframe_bytes
from app.services.notebook_preprocessing import capture_notebook
from app.services.notebook_qc import _source, _definition, _merge_source, _replace_once
from app.services.notebook_source import extract_notebook_source
from app.services.notebook_ora import ora_source, GO_ATTRIBUTION
from app.services.notebook_volcano import volcano_source


@lru_cache(maxsize=1)
def pathway_source():
    original = _source('stats_tools.py')
    function = _definition(original, 'pathway_heatmap_png')
    boundary = function.index('    fig, ax = plt.subplots')
    prepare = function[:boundary] + '    return heatmap_data, total_genes, color_label\n'
    prepare = _replace_once(prepare, 'def pathway_heatmap_png(\n    *,',
                           'def prepare_matrix(data, metadata, database, *, centered=False,')
    prepare = _replace_once(prepare, '    plt = _get_plt()\n    _, frame, metadata, _ = _stats_source(kind, data_source=data_source)',
                           '    frame = data')
    prepare = _replace_once(prepare, '    db = load_go_db()', '    db = database')
    prepare = _replace_once(prepare, '_phosprot_values_are_centred(kind)', 'centered')
    for parameter in ('    header: bool,\n', '    width_cm: float,\n', '    height_cm: float,\n',
                      '    dpi: int,\n', '    data_source: str = "data",\n', '    advanced: dict | None = None,\n'):
        prepare = _replace_once(prepare, parameter, '')
    prepare = prepare.replace(') -> bytes:', '):').replace('AnnotationKind', 'str').replace('HeatmapValueType', 'str')
    prepare = prepare.replace('_extract_id_or_number(', 'extract_sample_id(')
    render = ('def render_plot(heatmap_data, total_genes, color_label, *, pathway, value_type, header, '
              'width_cm, height_cm, dpi, advanced=None):\n    plt = get_plt()\n' + function[boundary:])
    helpers = '\n\n'.join(_definition(original, name) for name in (
        '_aggregate_pathway_gene_values', '_gene_tokens', '_wrapped_title'))
    code = _merge_source('import numpy as np\nimport pandas as pd\n'
        'from scipy.cluster.hierarchy import leaves_list, linkage\nfrom scipy.spatial.distance import pdist',
        extract_notebook_source(ora_source().code, ('get_plt', 'to_png_bytes', 'cm_to_inch',
            'fit_figure_to_labels', 'advanced_color_map', 'advanced_label', 'apply_advanced_axes', '_wrap_to_width')).code,
        extract_notebook_source(volcano_source().code, ('_first_available_column', '_gene_label_candidates')).code,
        extract_notebook_source(_source('clustering_tools.py'), ('row_zscore', 'drop_incomplete_features', 'heatmap_notice')).code,
        extract_notebook_source(_source('functions.py'), ('intensity_unit_label', 'extract_sample_id')).code,
        helpers, prepare, render)
    for before, after in (('_cm_to_inch(', 'cm_to_inch('), ('_to_png_bytes(', 'to_png_bytes('),
                          ('_fit_figure_to_labels(', 'fit_figure_to_labels(')):
        code = code.replace(before, after)
    return extract_notebook_source(code, ('prepare_matrix', 'render_plot'))


@lru_cache(maxsize=1)
def pathway_module():
    module = ModuleType('_copylot_portable_pathway')
    sys.modules[module.__name__] = module
    exec(pathway_source().code, module.__dict__)
    return module


def render_pathway(**options):
    from app.services import stats_tools
    from app.services.annotation_store import get_annotation
    from app.services.dataset_store import get_current_dataset
    from app.services.functions import _phosprot_values_are_centred
    from app.services.notebook_provenance import input_history
    from app.services.plot_export import plot_output_format
    from app.services.runtime_cache import runtime_cache_version
    from app.services.session_context import get_session_id

    revision = runtime_cache_version()
    bound = inspect.signature(stats_tools.pathway_heatmap_png).bind(**options)
    bound.apply_defaults()
    settings = dict(bound.arguments)
    kind = settings['kind']
    source, data, metadata, warnings = stats_tools._stats_source(kind, data_source=settings['data_source'])
    annotation, dataset = get_annotation(kind), get_current_dataset(kind)
    lineage, imputation, uses_imputed, imputation_text = input_history(kind, annotation, dataset, source=source)
    settings.update(data_source=source, centered=_phosprot_values_are_centred(kind))
    metadata = metadata[['sample', 'condition']].copy(deep=True)
    if settings['conditions']:
        metadata = metadata.loc[metadata['condition'].isin(settings['conditions'])].copy()
    columns = list(dict.fromkeys(metadata['sample'].astype(str).tolist() + ['GeneNames', 'Gene_group']))
    data = data[[c for c in columns if c in data]].copy(deep=True)
    database = stats_tools.load_go_db()
    membership = database.loc[database['description'].astype(str).str.lower() == settings['pathway'].strip().lower()]
    membership = membership[['ontology', 'term', 'description', 'genes']].head(1).copy(deep=True)
    module = pathway_module()
    preparation = {key: value for key, value in settings.items()
                   if key not in {'header', 'width_cm', 'height_cm', 'dpi', 'data_source', 'advanced'}}
    matrix, total, color_label = module.prepare_matrix(data, metadata, membership, **preparation)
    figure_settings = {key: settings[key] for key in ('pathway', 'value_type', 'header', 'width_cm', 'height_cm', 'dpi', 'advanced')}
    fmt = plot_output_format.get()
    format_token = module.plot_output_format.set(fmt)
    try:
        content = module.render_plot(matrix, total, color_label, **figure_settings)
    finally:
        module.plot_output_format.reset(format_token)
    recipe = NotebookRecipe(plot_name='Pathway Heatmap', source=pathway_source(),
        original_filename=dataset.filename, settings={'preparation': preparation, 'figure': figure_settings},
        resources={'input.parquet': dataframe_bytes(data), 'metadata.parquet': dataframe_bytes(metadata),
            'pathway.parquet': dataframe_bytes(membership), 'matrix.parquet': dataframe_bytes(matrix),
            f'original.{fmt}': bytes(content), 'GO_ATTRIBUTION.txt': GO_ATTRIBUTION},
        uses_imputed_input=uses_imputed, imputation_recipe=imputation_text,
        provenance=dict(kind=kind, plot='pathway', sourceUsed=source, warnings=warnings,
            databaseSha256=stats_tools._go_database_sha256(), totalPathwayGenes=total, displayedGenes=len(matrix),
            normalization=annotation.filter_config.normalization, filter=annotation.filter_config.model_dump(),
            upstreamCollapse=lineage.model_dump() if lineage else None,
            imputation=imputation.model_dump() if imputation else None),
        input_explanation='The exact selected log2 matrix is frozen after normalization, filtering and any collapse. '
            'The notebook repeats pathway gene matching, per-sample median aggregation, optional row z-scores, '
            'missing-row exclusions, sample labels and clustering. The captured GO record is the first matching '
            'description, exactly as in the app. Imputed values are never drawn again.',
        calculation="from IPython.display import display, Image\n"
            "pathway = pd.read_parquet(RESOURCES / 'pathway.parquet')\n"
            "matrix, total, color_label = functions.prepare_matrix(data, metadata, pathway, **settings['preparation'])\n"
            "pd.testing.assert_frame_equal(matrix, pd.read_parquet(RESOURCES / 'matrix.parquet'), check_exact=True)\n"
            "matrix.to_csv('reproduced_heatmap_matrix.csv', index=True)\ndisplay(matrix)\n"
            "image = functions.render_plot(matrix, total, color_label, **settings['figure'])\n"
            "Path('reproduced.png').write_bytes(image)\ndisplay(Image(data=image))")
    try:
        token = capture_notebook(get_session_id(), recipe) if runtime_cache_version() == revision else ''
    except ValueError:
        token = ''
    return content, token
