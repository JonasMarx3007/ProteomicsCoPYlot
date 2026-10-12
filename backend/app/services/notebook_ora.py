"""Standalone ORA calculation and plotting code, using an explicit database."""
import ast
import json
from functools import lru_cache
import sys
from types import ModuleType, SimpleNamespace

from app.services.notebook_source import extract_notebook_source, function_definition, merge_source, module_source, replace_once
from app.services.notebook_archive import NotebookRecipe, dataframe_bytes
from app.services.notebook_preprocessing import capture_notebook
from app.services.notebook_volcano import volcano_source

GO_ATTRIBUTION = (
    'Gene Ontology Consortium, copyright 1999-present. CC BY 4.0: '
    'https://creativecommons.org/licenses/by/4.0/\n'
    'Source and citation policy: https://geneontology.org/docs/go-citation-policy/\n'
    'GO term-to-gene mapping (human or mouse; the organism is recorded in provenance) built for CoPYlot '
    'from the GO Consortium release recorded in data/db/README.md and data/reference-sources/manifest.json '
    'of the CoPYlot repository; serialized as Parquet for this export. No warranties. '
    'The original database checksum is recorded in provenance; resource checksums identify this export.\n').encode()


@lru_cache(maxsize=3)
def ora_source(upstream=None):
    original = module_source("stats_tools.py")
    universe = function_definition(original, "_prepare_ora_universe")
    universe = replace_once(universe, "def _prepare_ora_universe(", "def prepare_universe(database,")
    universe = replace_once(universe, "db = load_go_db(organism)", "db = database")
    enrichment = function_definition(original, "_enrichment_terms").replace("EnrichmentTerm", "SimpleNamespace")
    rendering = function_definition(original, "ora_plot_png")
    rendering = replace_once(rendering, "def ora_plot_png(", "def render_plot(result, request,")
    rendering = replace_once(rendering, "    payload: EnrichmentRequest,\n", "")
    rendering = replace_once(rendering, "    result = run_enrichment(payload)",
        "    payload = SimpleNamespace(**request)\n"
        "    result = SimpleNamespace(**{key: [SimpleNamespace(**term) for term in value]\n"
        "        if key in {'upTerms', 'downTerms', 'clusterTerms'} else value\n"
        "        for key, value in result.items()})")
    helpers = "\n\n".join(function_definition(original, name) for name in (
        "_ora_direction_texts", "_rc_font_points", "_ora_height_needed_cm", "_ora_height_ceiling_cm",
        "_ora_label_layout", "_wrap_to_width"))
    constants = "\n\n".join(ast.get_source_segment(original, node) for node in ast.parse(original).body
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and any(
            isinstance(part, ast.Name) and (part.id.startswith("_ORA_") or part.id == "_POINTS_TO_CM")
            for part in ast.walk(node)))
    styling = "\n".join(line for line in module_source("plot_styling.py").splitlines()
                        if not line.startswith("from app."))
    calculation = '''
def calculate_enrichment(database, query_genes, background_genes, *, min_term_size=20,
                         max_term_size=300, top_n=10, adj_p_value_cutoff=0.05):
    if min_term_size > max_term_size:
        raise ValueError("Minimum term size cannot be larger than maximum term size.")
    background, eligible = prepare_universe(database, background_genes, min_term_size, max_term_size)
    counts = {}
    terms = _enrichment_terms(query_genes, top_n, adj_p_value_cutoff, background, eligible, counts)
    return {"terms": [vars(term) for term in terms], "counts": counts,
            "annotatedBackground": sorted(background)}

def export_term_rows(result, request, direction):
    context = dict(method='ORA', organism=result['organism'], analysisSource=request['source'],
                   datasetLevel=result['kind'], dataSource=result['sourceUsed'])
    context.update({key: result[key] for key in ('backgroundMode', 'backgroundSize',
        'annotatedBackgroundSize', 'correctionMethod', 'upstreamCorrectionMethod', 'testedTermCount')})
    context.update(result['termCounts'][direction])
    if direction == 'cluster':
        keys = ['selectedCluster', 'pValueThreshold', 'useUncorrected', 'nClusters', 'clusterMethod']
    else:
        context.update(direction=direction, condition1=request['condition1'], condition2=request['condition2'],
            condition1Control=request['condition1Control'] if request['source'] == 'volcano_control' else '',
            condition2Control=request['condition2Control'] if request['source'] == 'volcano_control' else '')
        keys = ['testType', 'pValueThreshold', 'log2fcThreshold', 'useUncorrected']
    keys += ['adjPValueCutoff', 'minTermSize', 'maxTermSize']
    context.update({key: request[key] for key in keys})
    return [dict(context, **term) for term in result[f'{direction}Terms']]
'''
    code = merge_source(
        "import numpy as np\nimport pandas as pd\nfrom types import SimpleNamespace\nfrom scipy.stats import hypergeom",
        extract_notebook_source(volcano_source().code, ("_bh_adjust", "_safe_neg_log10", "get_plt",
            "advanced_label", "advanced_number", "apply_advanced_axes")).code,
        extract_notebook_source(styling, ("advanced_color_map", "advanced_element_number")).code,
        extract_notebook_source(module_source("plot_export.py"), (
            "to_png_bytes", "cm_to_inch", "fit_figure_to_labels", "MAX_AUTO_FIT_CM", "MAX_AUTO_FIT_PIXELS")).code,
        constants, helpers, universe, enrichment, calculation, rendering)
    for before, after in (("EnrichmentRequest", "SimpleNamespace"), ("EnrichmentResultResponse", "SimpleNamespace"),
                          ("OraDirection", "str"), ("_get_plt()", "get_plt()"),
                          ("_to_png_bytes(", "to_png_bytes("), ("_cm_to_inch(", "cm_to_inch("),
                          ("_fit_figure_to_labels(", "fit_figure_to_labels(")):
        code = code.replace(before, after)
    roots = ("calculate_enrichment", "render_plot", "export_term_rows")
    if upstream:
        if upstream == "anova":
            from app.services.notebook_anova import anova_source
            scientific = extract_notebook_source(anova_source().code, ("calculate_tables",)).code
            selection = '''
    result = calculate_tables(data, metadata, settings['upstream'], imputation_mask)
    label = result['labelColumn']
    table = pd.DataFrame(result['rows'])
    clusters = pd.DataFrame(result['clusterRows'])
    selected = clusters.loc[clusters['cluster'] == settings['request']['selectedCluster']]
    queries = {'cluster': selected[label].tolist()}
'''
        elif upstream == "volcano":
            scientific = extract_notebook_source(volcano_source().code, ("calculate_table",)).code
            selection = '''
    _, label, table, _ = calculate_table(data, metadata, imputation_mask, **settings['upstream'])
    queries = {direction: table.loc[table['significance'] == significance, label].tolist()
               for direction, significance in [('up', 'Upregulated'), ('down', 'Downregulated')]}
'''
        else:
            raise ValueError("Unsupported ORA upstream calculation.")
        select = "def select_queries(data, metadata, imputation_mask, settings):\n" + selection + '''
    split_groups = settings['request']['kind'] == 'phosprot' or label == 'Gene_group'
    return ({key: _genes_from_values(values, split_groups=split_groups) for key, values in queries.items()},
            _genes_from_values(table[label].tolist(), split_groups=split_groups))
'''
        code = merge_source(code, scientific, select, function_definition(original, "_genes_from_values"),
            function_definition(original, "_gene_tokens"), function_definition(original, "_clean_feature_name"))
        roots += ("select_queries",)
    return extract_notebook_source(code, roots)


@lru_cache(maxsize=3)
def ora_module(upstream=None):
    module = ModuleType(f"_copylot_portable_ora_{upstream or 'terms'}")
    sys.modules[module.__name__] = module
    exec(ora_source(upstream).code, module.__dict__)
    return module


def render_ora(payload, *, direction, advanced=None, width_cm=26, height_cm=12, dpi=300, table_only=False):
    from app.schemas.stats import AnovaRequest
    from app.services import stats_tools
    from app.services.annotation_store import get_annotation
    from app.services.dataset_store import get_current_dataset
    from app.services.notebook_provenance import input_history, NotebookProvenanceError
    from app.services.plot_export import plot_output_format
    from app.services.runtime_cache import runtime_cache_version
    from app.services.session_context import get_session_id

    revision = runtime_cache_version()
    result = stats_tools.run_enrichment(payload).model_dump()
    source, data, metadata, _ = stats_tools._stats_source(payload.kind, data_source=payload.dataSource)
    annotation, dataset = get_annotation(payload.kind), get_current_dataset(payload.kind)
    lineage, imputation, uses_imputed, imputation_text = input_history(payload.kind, annotation, dataset, source=source)
    metadata = metadata[[c for c in ('sample', 'condition', 'pair_id') if c in metadata]].copy(deep=True)
    mask = stats_tools._imputation_mask(payload.kind, source, data, metadata['sample'].astype(str).tolist())
    columns = list(dict.fromkeys(metadata['sample'].astype(str).tolist() + [
        'GeneNames', 'Gene_group', 'ProteinNames', 'Protein_group', 'PTM_Collapse_key',
        'Phosphoprotein', 'site_num', 'PTM_Collapse_keys']))
    data = data[[c for c in columns if c in data]].copy(deep=True)
    mode = 'anova' if payload.source == 'anova' else 'volcano'
    if mode == 'anova':
        upstream = AnovaRequest(kind=payload.kind, source='anova_cluster', dataSource=source,
            identifier='genes', pValueThreshold=payload.pValueThreshold, useUncorrected=payload.useUncorrected,
            nClusters=payload.nClusters, clusterMethod=payload.clusterMethod).model_dump()
    else:
        upstream = dict(kind=payload.kind, data_source=source, identifier='genes', condition1=payload.condition1,
            condition2=payload.condition2, p_value_threshold=payload.pValueThreshold,
            log2fc_threshold=payload.log2fcThreshold, test_type=payload.testType, use_uncorrected=payload.useUncorrected)
        if payload.source == 'volcano_control':
            upstream.update(condition1_control=payload.condition1Control, condition2_control=payload.condition2Control)
    settings = dict(request=payload.model_dump(), upstream=upstream,
        enrichment=dict(min_term_size=payload.minTermSize, max_term_size=payload.maxTermSize,
                        top_n=payload.topN, adj_p_value_cutoff=payload.adjPValueCutoff),
        figure=dict(direction=direction, advanced=advanced, width_cm=width_cm, height_cm=height_cm, dpi=dpi))
    module = ora_module(mode)
    queries, tested = module.select_queries(data, metadata, mask, settings)
    database = stats_tools.load_go_db(payload.organism)[['ontology', 'term', 'description', 'genes']].copy(deep=True)
    background = tested if payload.backgroundMode == 'experiment' else None
    for key, genes in queries.items():
        calculated = module.calculate_enrichment(database, genes, background, **settings['enrichment'])
        if (genes != result[f'{key}Genes'] or calculated['terms'] != result[f'{key}Terms']
                or calculated['counts'] != result['termCounts'][key]
                or len(calculated['annotatedBackground']) != result['annotatedBackgroundSize']):
            raise NotebookProvenanceError("The upstream ORA snapshot changed; render again.")
    if background is not None and background != result['backgroundGenes']:
        raise NotebookProvenanceError("The ORA background changed; render again.")
    module._ora_direction_texts(SimpleNamespace(**settings['request']), SimpleNamespace(**result), direction, advanced)
    fmt = plot_output_format.get()
    format_token = module.plot_output_format.set(fmt)
    try:
        content = b'' if table_only else module.render_plot(result, settings['request'], **settings['figure'])
    finally:
        module.plot_output_format.reset(format_token)
    resources = {'input.parquet': dataframe_bytes(data), 'metadata.parquet': dataframe_bytes(metadata),
        'database.parquet': dataframe_bytes(database), 'result.json': json.dumps(result, allow_nan=False).encode(),
        'GO_ATTRIBUTION.txt': GO_ATTRIBUTION}
    if content:
        resources[f'original.{fmt}'] = bytes(content)
    if mask is not None:
        resources['imputation_mask.parquet'] = dataframe_bytes(mask)
    recipe = NotebookRecipe(plot_name=f'ORA {direction}', source=ora_source(mode), settings=settings,
        original_filename=dataset.filename, resources=resources, uses_imputed_input=uses_imputed,
        imputation_recipe=imputation_text,
        provenance=dict(kind=payload.kind, plot='ora', direction=direction, sourceUsed=source,
            request=payload.model_dump(), databaseSha256=result['databaseSha256'], organism=result['organism'],
            normalization=annotation.filter_config.normalization, filter=annotation.filter_config.model_dump(),
            upstreamCollapse=lineage.model_dump() if lineage else None,
            imputation=imputation.model_dump() if imputation else None),
        input_explanation='The exact selected log2 matrix is frozen after normalization, filtering and any collapse. '
            'The notebook reruns the upstream statistical comparison or ANOVA clustering, selects genes and '
            'recalculates ORA against the captured full database. Imputation is never redrawn.',
        calculation="from IPython.display import display, Image\n"
            "mask_path = RESOURCES / 'imputation_mask.parquet'\n"
            "mask = pd.read_parquet(mask_path) if mask_path.exists() else None\n"
            "database = pd.read_parquet(RESOURCES / 'database.parquet')\n"
            "result = json.loads((RESOURCES / 'result.json').read_text())\n"
            "queries, tested = functions.select_queries(data, metadata, mask, settings)\n"
            "background = tested if settings['request']['backgroundMode'] == 'experiment' else None\n"
            "if background is not None:\n    assert background == result['backgroundGenes']\n"
            "for direction, genes in queries.items():\n"
            "    assert genes == result[f'{direction}Genes']\n"
            "    calculated = functions.calculate_enrichment(database, genes, background, **settings['enrichment'])\n"
            "    assert calculated['terms'] == result[f'{direction}Terms']\n"
            "    assert calculated['counts'] == result['termCounts'][direction]\n"
            "    assert len(calculated['annotatedBackground']) == result['annotatedBackgroundSize']\n"
            "    result[f'{direction}Terms'] = calculated['terms']\n"
            "    table = pd.DataFrame(functions.export_term_rows(result, settings['request'], direction))\n"
            "    table.to_csv(f'reproduced_{direction}_terms.csv', index=False)\n    display(table)\n"
            "    Path(f'{direction}_genes.txt').write_text('\\n'.join(genes), encoding='utf-8', newline='')\n"
            "Path('tested_genes.txt').write_text('\\n'.join(tested), encoding='utf-8', newline='')\n"
            "Path('annotated_background_genes.txt').write_text('\\n'.join(calculated['annotatedBackground']), encoding='utf-8', newline='')\n"
            "if result[settings['figure']['direction'] + 'Terms']:\n"
            "    image = functions.render_plot(result, settings['request'], **settings['figure'])\n"
            "    Path('reproduced.png').write_bytes(image)\n    display(Image(data=image))\n"
            "else:\n    print('No enriched terms passed the selected parameters; no plot is generated.')")
    try:
        token = capture_notebook(get_session_id(), recipe) if runtime_cache_version() == revision else ''
    except ValueError:
        token = ''
    return content, token
