"""Table-only Kinase Library preparation; no plotting or external analysis."""
from functools import lru_cache
import inspect
import json
import logging

from app.services.notebook_archive import NotebookRecipe, dataframe_bytes
from app.services.notebook_preprocessing import capture_notebook
from app.services.notebook_qc import _source, _definition, _replace_once, _merge_source
from app.services.notebook_source import extract_notebook_source
from app.services.notebook_volcano import volcano_source

LOGGER = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def table_source():
    original = _source('phospho_tools.py')
    formatter = _definition(original, '_ksea_format')
    formatter = _replace_once(formatter, 'def _ksea_format(frame: pd.DataFrame, organism: str)',
                              'def format_table(frame: pd.DataFrame, sequences)')
    formatter = _replace_once(formatter, '    sequences = _ksea_protein_sequences(organism)\n', '')
    original = original.replace(_definition(original, '_ksea_format'), formatter)
    return extract_notebook_source(_merge_source(
        extract_notebook_source(volcano_source().code, ('calculate_table',)).code,
        extract_notebook_source(original, ('format_table',)).code), ('calculate_table', 'format_table'))


def capture_table(**options):
    from app.services import phospho_tools
    from app.services.runtime_cache import runtime_cache_version
    from app.services.session_context import get_session_id

    revision = runtime_cache_version()
    bound = inspect.signature(phospho_tools.ksea_table).bind(**options)
    bound.apply_defaults()
    settings = dict(bound.arguments)
    settings['source'] = str(settings['source']).strip().lower()
    settings['data_source'] = str(settings['data_source']).strip().lower()
    settings['organism'] = phospho_tools._resolve_ksea_organism(settings['organism'])
    # Retain the app's validation and exact displayed table.
    table = phospho_tools.ksea_table(**settings)
    try:
        recipe = _table_recipe(settings, table)
    except Exception:  # noqa: BLE001 -- the table the user asked for is ready; only its notebook is not.
        LOGGER.exception('Could not prepare the Kinase Library notebook')
        return table, ''
    try:
        token = capture_notebook(get_session_id(), recipe) if runtime_cache_version() == revision else ''
    except ValueError:
        token = ''
    return table, token


def _table_recipe(settings, table):
    from app.services import phospho_tools, stats_tools
    from app.services.annotation_store import get_annotation
    from app.services.dataset_store import get_current_dataset
    from app.services.notebook_provenance import input_history
    from app.services.phospho_localization import get_localization_cutoff

    source, data, metadata, _ = stats_tools._stats_source('phospho', data_source=settings['data_source'])
    metadata = metadata[[c for c in ('sample', 'condition', 'pair_id') if c in metadata]].copy(deep=True)
    mask = stats_tools._imputation_mask('phospho', source, data, metadata['sample'].astype(str).tolist())
    identifiers = ['GeneNames', 'Gene_group', 'ProteinNames', 'PTM_Collapse_key', 'UPD_seq',
                   'Protein_group', 'Phosphoprotein', 'site_num', 'PTM_Collapse_keys']
    data = data[[c for c in dict.fromkeys([*metadata['sample'].tolist(), *identifiers]) if c in data]].copy(deep=True)
    annotation, dataset = get_annotation('phospho'), get_current_dataset('phospho')
    _, imputation, uses_imputed, documentation = input_history('phospho', annotation, dataset, source)
    calculation = {key: settings[key] for key in ('condition1', 'condition2', 'data_source',
        'p_value_threshold', 'log2fc_threshold', 'test_type', 'use_uncorrected')}
    calculation.update(kind='phospho', identifier='workflow')
    if settings['source'] == 'volcano_control':
        calculation.update(condition1_control=settings['condition1_control'], condition2_control=settings['condition2_control'])
    sequences = phospho_tools._ksea_protein_sequences(settings['organism']) or {}
    accessions = set()
    # A table identified only by UPD_seq has no site keys; the peptide fallback then builds the windows.
    for key in (data['PTM_Collapse_key'] if 'PTM_Collapse_key' in data else ()):
        parsed = phospho_tools._parse_site_key(key)
        if parsed:
            accessions.update(parsed[0])
    sequences = {key: sequences[key] for key in sorted(accessions) if key in sequences}
    resources = {'input.parquet': dataframe_bytes(data), 'metadata.parquet': dataframe_bytes(metadata),
        'table.parquet': dataframe_bytes(table), 'sequences.json': json.dumps(sequences).encode('utf-8')}
    if mask is not None:
        resources['imputation_mask.parquet'] = dataframe_bytes(mask)
    if sequences:
        resources['REFERENCE_LICENSE.txt'] = (
            'Reference protein sequences: UniProt Consortium. https://www.uniprot.org/\n'
            'CC BY 4.0: https://creativecommons.org/licenses/by/4.0/\n'
            'Subset of the CoPYlot bundled reference proteome; no sequences modified.\n').encode()
    recipe = NotebookRecipe(plot_name='Kinase Library Input Table', source=table_source(),
        settings={'request': settings, 'calculation': calculation}, original_filename=dataset.filename,
        uses_imputed_input=uses_imputed, imputation_recipe=documentation, resources=resources,
        provenance={'kind': 'phospho', 'output': 'ksea_input_table', 'sourceUsed': source,
            'localizationCutoff': get_localization_cutoff(), 'filter': annotation.filter_config.model_dump(),
            'imputation': imputation.model_dump() if imputation else None},
        input_explanation='Table preparation only, with no plotting and no external enrichment analysis. '
            'The notebook recalculates the statistics from the captured processed matrix and pairing metadata, '
            'then constructs motif windows using the captured reference subset or peptide fallback. '
            'Imputed values are frozen. Original-upload preprocessing is documented, not rerun.',
        calculation="mask_path = RESOURCES / 'imputation_mask.parquet'\n"
            "mask = pd.read_parquet(mask_path) if mask_path.exists() else None\n"
            "_, _, statistics, _ = functions.calculate_table(data, metadata, mask, **settings['calculation'])\n"
            "if settings['request']['source'] == 'volcano_control':\n"
            "    statistics = pd.DataFrame(statistics.astype(object).where(pd.notna(statistics), None).to_dict(orient='records'))\n"
            "sequences = json.loads((RESOURCES / 'sequences.json').read_text(encoding='utf-8'))\n"
            "table = functions.format_table(statistics, sequences)\n"
            "pd.testing.assert_frame_equal(table, pd.read_parquet(RESOURCES / 'table.parquet'), check_exact=True)\n"
            "table.to_csv('KinaseLibrary_input.tsv', sep='\\t', index=False)\n"
            "from IPython.display import display\ndisplay(table)")
    return recipe
