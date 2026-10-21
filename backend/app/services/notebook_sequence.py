"""Offline sequence coverage from the selected peptides and reference record."""
from functools import lru_cache
import json
import sys
from types import ModuleType

from app.services.notebook_archive import NotebookRecipe, dataframe_bytes
from app.services.notebook_preprocessing import capture_notebook
from app.services.notebook_source import extract_notebook_source, function_definition, module_source, replace_once


@lru_cache(maxsize=1)
def sequence_source():
    original = module_source('peptide_tools.py')
    function = function_definition(original, 'peptide_sequence_coverage')
    function = replace_once(function, 'def peptide_sequence_coverage(\n    *,', 'def calculate(data, database, *,')
    function = replace_once(function, '    frame = get_peptide_frame()', '    frame = data')
    function = replace_once(function, '    db = _load_fasta_dataframe(species)', '    db = database')
    # The notebook carries the selected record itself; no bundled file is consulted on a miss.
    function = replace_once(function, '    sequence = _fasta_sequence(db, protein, species)', '    sequence = _fasta_sequence(db, protein)')
    function = replace_once(function, '        raise ValueError(_missing_variant_message(species, protein))',
                            '        raise ValueError(f"The selected protein variant \'{protein}\' is not the record carried by this notebook.")')
    function = function.replace('species: PeptideSpecies', 'species: str')
    original = original.replace(function_definition(original, 'peptide_sequence_coverage'), function)
    original = replace_once(original, '    if species is not None:\n        additional = _load_additional_fasta_dataframe(species)\n'
                            '        if additional is not None:\n            return _fasta_sequence(additional, identifier)\n    return None\n',
                            '    return None\n')
    original = replace_once(original, 'def _fasta_sequence(db: pd.DataFrame, protein: str, species: PeptideSpecies | None = None) -> str | None:',
                            'def _fasta_sequence(db: pd.DataFrame, protein: str, species: str | None = None) -> str | None:')
    return extract_notebook_source(original, ('calculate',))


@lru_cache(maxsize=1)
def sequence_module():
    module = ModuleType('_copylot_portable_sequence_coverage')
    sys.modules[module.__name__] = module
    exec(sequence_source().code, module.__dict__)
    return module


def capture_sequence_coverage(*, species, protein, chunk_size=100):
    import pandas as pd
    from app.services import peptide_tools
    from app.services.dataset_store import get_current_dataset
    from app.services.runtime_cache import runtime_cache_version
    from app.services.session_context import get_session_id

    if not protein.strip():
        raise ValueError('A protein must be selected for sequence coverage.')
    revision = runtime_cache_version()
    dataset = get_current_dataset('peptide')
    frame = peptide_tools.get_peptide_frame()
    sequence_column = peptide_tools._stripped_sequence_column(frame)
    protein_column = peptide_tools._protein_names_column(frame)
    members = frame[protein_column].fillna('').astype(str).str.split(';')
    selected = members.map(lambda names: protein in [name.strip() for name in names])
    # The quantity decides which peptides were measured: a peptide never
    # quantified above 0 covers nothing. Dropping the column switched that rule off.
    columns = [protein_column, sequence_column]
    if 'Precursor.Quantity' in frame.columns:
        columns.append('Precursor.Quantity')
    data = frame.loc[selected, columns].copy(deep=True)
    database = peptide_tools._load_fasta_dataframe(species)
    reference = database.iloc[:0]
    for additional in (False, True):
        if additional:
            extra = peptide_tools._load_additional_fasta_dataframe(species)
            if extra is None:
                break
            database = extra
        for column in ('name', 'accession'):
            matches = database.loc[database[column].astype(str) == str(protein).strip()]
            if not matches.empty:
                reference = matches.head(1)
                break
        if not reference.empty:
            break
    reference = reference[['full_header', 'name', 'accession', 'V1']].copy(deep=True)
    settings = dict(species=species, protein=protein, chunk_size=chunk_size)
    result = sequence_module().calculate(data, reference, **settings)
    if dataset is None:
        return dict(result, notebookToken=None)
    result_bytes = json.dumps(result, ensure_ascii=False).encode('utf-8')
    recipe = NotebookRecipe(plot_name='Peptide Sequence Coverage', source=sequence_source(), settings=settings,
        original_filename=dataset.filename,
        resources={'input.parquet': dataframe_bytes(data), 'metadata.parquet': dataframe_bytes(pd.DataFrame()),
            'reference.parquet': dataframe_bytes(reference), 'result.json': result_bytes,
            'original.txt': result['sequenceText'].encode('utf-8'),
            'REFERENCE_ATTRIBUTION.txt': b'Selected record from the bundled UniProt reference proteome FASTA.\n'
                b'Attribution: UniProt Consortium. https://www.uniprot.org/\n'
                b'License: CC BY 4.0 https://creativecommons.org/licenses/by/4.0/\n'
                b'Policy: https://www.uniprot.org/help/license\n'
                b'The selected record is serialized as Parquet; its sequence is unchanged.\n'
                b'The release of the bundled proteome is recorded in data/db/README.md of the CoPYlot '
                b'repository (UniProt 2026_03 since 2026-10-12). No warranties are provided.\n'},
        provenance={'kind': 'peptide', 'output': 'sequence_coverage', 'species': species,
            'referenceAccession': str(reference.iloc[0]['accession']),
            'referenceRelease': 'recorded in data/db/README.md of the CoPYlot repository', 'normalizationApplied': False, 'imputationApplied': False,
            'selection': 'unique stripped sequences assigned to the exact selected protein-group member, '
                'measured above 0 in at least one row when the file has Precursor.Quantity'},
        input_explanation='Only peptide rows assigned to the selected protein and the exact selected reference '
            'sequence are captured. The notebook repeats unique peptide selection (peptides never quantified above 0 cover nothing), all overlapping occurrence '
            'matching, the covered-position union, unmapped-peptide reporting and the chunked text layout. '
            'Reference lookup used entry name before accession, with the first matching record. No internet '
            'lookup, normalization or imputation is used.',
        calculation="reference = read_resource_table(RESOURCES / 'reference.parquet')\n"
            "result = functions.calculate(data, reference, **settings)\n"
            "assert result == json.loads((RESOURCES / 'result.json').read_text(encoding='utf-8'))\n"
            "Path('reproduced_coverage.txt').write_text(result['sequenceText'], encoding='utf-8', newline='')\n"
            "Path('reproduced_summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8', newline='')\n"
            "print(result['sequenceText'])\nprint(f\"Coverage: {result['coveragePercent']}%\")")
    try:
        token = capture_notebook(get_session_id(), recipe) if runtime_cache_version() == revision else ''
    except ValueError:
        token = ''
    return dict(result, notebookToken=token or None)
