"""Supply a synthetic original upload when executing exported notebooks in tests."""
import json

from app.services.annotation_store import get_annotation


def set_original_path(cells, directory):
    manifest = json.loads((directory / 'manifest.json').read_text())
    provenance = manifest['provenance']
    if provenance.get('inputReplay') != 'original-file':
        return cells
    original = directory / 'test-original.parquet'
    kind = 'phospho' if 'upstream' in provenance['preprocessing'] else provenance['kind']
    if kind in {'peptide', 'precursor'}:
        from app.services.peptide_tools import get_peptide_frame
        frame = get_peptide_frame()
    else:
        frame = get_annotation(kind).source_data
    frame.to_parquet(original, index=True)
    return cells.replace("Path('YOUR_ORIGINAL_DATA_FILE')", "Path('test-original.parquet')")
