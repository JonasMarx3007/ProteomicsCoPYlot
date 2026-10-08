"""Verified original-file preprocessing for table-backed notebook exports."""
from dataclasses import replace
from contextvars import ContextVar
from functools import lru_cache
import io
import json
import ast
from types import ModuleType

import pandas as pd

from app.services.notebook_archive import dataframe_bytes
from app.services.notebook_provenance import NotebookProvenanceError
from app.services.notebook_snapshots import RetainedReplay
from app.services.notebook_source import extract_notebook_source
from app.services.dataset_reader import rename_cols, sanitize_dataframe
from app.services.annotation_processor import prepare_normalized_log2_data
from app.services.id_translation import replay_id_translations
from app.services.functions import filter_data, filter_localization, inverse_log2_transform_data, raw_zero_to_nan
from app.services.phosprot_tools import transform_phosprot


report_recipe_sink = ContextVar('report_recipe_sink', default=None)


def capture_notebook(session, recipe):
    """Snapshot a rendered output for export; '' when this render gets no notebook.

    A plot render only binds the replay (see `bind_original_preprocessing`); it
    is prepared and checked when the ZIP is downloaded. A report prepares every
    section at once, because the report is one deliberate export.
    """
    from copy import deepcopy
    from app.services.notebook_qc import snapshots
    from app.services.notebook_snapshots import PendingRecipe
    from app.services.plot_export import notebook_capture_allowed
    from app.services.runtime_cache import runtime_cache_version
    from app.services.viewer_bootstrap import viewer_mode_enabled
    sink = report_recipe_sink.get()
    if sink is None and (not notebook_capture_allowed.get() or viewer_mode_enabled()):
        return ''
    from app.services.plot_export import note_notebook_unavailable
    try:
        revision = runtime_cache_version()
        recipe = deepcopy(recipe)
        finish = bind_original_preprocessing(recipe)
        if sink is not None:
            recipe = finish()
        if runtime_cache_version() != revision:
            raise NotebookProvenanceError('The dataset changed during notebook preparation; render again.')
        if sink is not None:
            sink(recipe)
            return 'report-section'
        return snapshots.capture(session, PendingRecipe(recipe, finish))
    except ValueError as exc:
        # The adapters keep the plot and drop the token; the page says why.
        note_notebook_unavailable(exc)
        raise


def read_original_table(path):
    """Use the upload reader's column aliases and missing identifier handling."""
    from pathlib import Path
    path = Path(path)
    extension = path.suffix.lower()
    if extension in {'.csv', '.tsv', '.txt'}:
        chunks = list(pd.read_csv(path, sep=',' if extension == '.csv' else '\t', chunksize=50_000))
        frame = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
    elif extension == '.xlsx':
        import openpyxl  # noqa: F401 -- pandas reads the original workbook with it.
        frame = pd.read_excel(path)
    elif extension == '.parquet':
        import pyarrow.parquet as pq
        parquet = pq.ParquetFile(path)
        batches = [batch.to_pandas() for batch in parquet.iter_batches(batch_size=50_000)]
        frame = (pd.concat(batches, ignore_index=True) if len(batches) > 1 else batches[0]) if batches else parquet.read().to_pandas()
    else:
        raise ValueError('Use the original CSV, TSV, TXT, XLSX or Parquet upload.')
    return sanitize_dataframe(rename_cols(frame))


def replay_preprocessing(raw, metadata, config):
    raw = replay_id_translations(raw, config.get('id_translations', []))
    samples = metadata['sample'].tolist()
    if config.get('vsn_runtime') and vsn_runtime_version() != config['vsn_runtime']:
        raise ValueError('Use the recorded R and Bioconductor vsn versions for this notebook.')
    if config['source'] == 'original_source_rows':
        data = raw.copy()
    elif config['source'] == 'source_data':
        data = raw.copy() if config['is_log2'] else raw_zero_to_nan(raw, samples)
    else:
        data = prepare_normalized_log2_data(raw, samples, config['is_log2'], config['normalization'])
        if config['source'] == 'filtered':
            filtering = config['filter']
            data = filter_data(data, metadata, min_present=filtering['minPresent'], mode=filtering['mode'],
                method=filtering['method'], min_percentage=filtering['minPercentage'])
    if config['kind'] == 'phospho':
        data = filter_localization(data, config['localization_cutoff'])
    if config['linear_output']:
        data = inverse_log2_transform_data(data, samples).reindex(columns=data.columns)
    return data


def replay_collapsed_input(raw, metadata, config):
    upstream_metadata = pd.DataFrame(config['upstream_metadata'])
    sites = replay_preprocessing(raw, upstream_metadata, config['upstream'])
    collapsed = transform_phosprot(sites, upstream_metadata, mode=config['aggregation'],
        data_scale='log2', coverage_data=sites)
    return replay_preprocessing(collapsed, metadata, config)


def vsn_runtime_version():
    import subprocess
    from app.services.r_runtime import detect_r_runtime
    executable = detect_r_runtime().get('executable')
    if not executable:
        raise ValueError('Install R and Bioconductor vsn to replay this normalization.')
    try:
        result = subprocess.run([str(executable), '-e',
            'cat(paste(getRversion(), as.character(packageVersion("vsn")), sep="|"))'],
            capture_output=True, text=True, check=True, timeout=60,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError('R and Bioconductor vsn must be available to replay this normalization.') from exc
    return result.stdout.strip()


@lru_cache(maxsize=4)
def preprocessing_source(collapse=False, vsn=False):
    from app.services.notebook_qc import _source, _definition, _merge_source, _replace_once
    functions = _source('functions.py')
    functions = _replace_once(functions, '        from app.services.r_vsn import vsn_normalize_linear', '')
    replay = _definition(_source('notebook_preprocessing.py'), 'replay_preprocessing')
    if not vsn:
        start = functions.index('    elif resolved == "vsn":', functions.index('def normalize_data('))
        end = functions.index('\n    else:\n        raise ValueError("Normalization must', start)
        functions = functions[:start] + functions[end:]
        replay = _replace_once(replay,
            "    if config.get('vsn_runtime') and vsn_runtime_version() != config['vsn_runtime']:\n"
            "        raise ValueError('Use the recorded R and Bioconductor vsn versions for this notebook.')\n", '')
    code = _merge_source(
        functions,
        extract_notebook_source(_source('dataset_reader.py'), ('rename_cols', 'sanitize_dataframe')).code,
        _definition(_source('annotation_processor.py'), 'prepare_normalized_log2_data'),
        _definition(_source('notebook_preprocessing.py'), 'read_original_table'),
        extract_notebook_source(_source('id_translation.py'), ('replay_id_translations',)).code,
        replay)
    if vsn:
        portable_runtime = ('import shutil\n\ndef detect_r_runtime():\n'
            '    executable = shutil.which("Rscript")\n'
            '    return {"available": bool(executable), "executable": executable}\n')
        vsn_code = _source('r_vsn.py').replace('from app.services.r_runtime import detect_r_runtime', '')
        version_code = _definition(_source('notebook_preprocessing.py'), 'vsn_runtime_version').replace(
            '    from app.services.r_runtime import detect_r_runtime\n', '')
        code = _merge_source(code, vsn_code, portable_runtime, version_code)
    root = 'replay_preprocessing'
    if collapse:
        collapse_code = _source('phosprot_tools.py').replace('PhosprotAggregationMode', 'str')
        # Resolve the original collapse's numeric helpers from the same scientific source.
        nodes = [node for node in ast.parse(collapse_code).body if not isinstance(node, ast.ImportFrom)
                 or not (node.module or '').startswith('app.')]
        collapse_code = '\n\n'.join(ast.get_source_segment(collapse_code, node) for node in nodes)
        code = _merge_source(code, collapse_code,
            _definition(_source('notebook_preprocessing.py'), 'replay_collapsed_input'))
        root = 'replay_collapsed_input'
    return extract_notebook_source(code, ('read_original_table', root))


def bind_original_preprocessing(recipe):
    """Read everything the replay needs from live state now; return the replay for later.

    Rendering a plot only binds: the processing settings, the metadata and a
    reference to the upload the annotation was built from. The expensive part --
    running the recorded preprocessing again and checking it reproduces the
    plot's input exactly, which for VSN means fitting it in R -- runs when the
    notebook is downloaded, so a plot nobody exports costs nothing extra. Nothing
    here is read from live state at download time.
    """
    from app.services.annotation_store import get_annotation
    from app.services.dataset_store import get_current_dataset
    from app.services.phospho_localization import get_localization_cutoff
    from app.services.notebook_qc import _merge_source

    if recipe.uses_imputed_input or recipe.provenance.get('inputReplay') == 'original-file':
        return lambda: recipe
    kind = recipe.provenance.get('kind')
    if kind in {'peptide', 'precursor'}:
        from app.services.notebook_peptide_preprocessing import bind_peptide_preprocessing
        return bind_peptide_preprocessing(recipe)
    if kind not in {'protein', 'phospho', 'phosprot'}:
        raise NotebookProvenanceError('This output has no original-file replay recipe.')
    annotation, dataset = get_annotation(kind), get_current_dataset(kind)
    if annotation is None or dataset is None:
        raise NotebookProvenanceError('Original-file processing history is unavailable.')
    if dataset.id_translations and not annotation.source_data.equals(dataset.frame):
        raise NotebookProvenanceError('Regenerate annotations after identifier translation before exporting a notebook.')
    source = recipe.provenance.get('sourceUsed', recipe.provenance.get('dataSource', 'data'))
    if source not in {'data', 'filtered', 'source_data', 'original_source_rows'}:
        raise NotebookProvenanceError('This source has no original-file replay recipe yet.')
    config = {'kind': kind, 'source': source, 'is_log2': annotation.is_log2_transformed,
        'normalization': annotation.filter_config.normalization,
        'filter': annotation.filter_config.model_dump(), 'localization_cutoff': get_localization_cutoff(),
        'linear_output': recipe.provenance.get('inputScale') in {'linear', 'linear ratios'},
        'id_translations': [step.model_dump() for step in dataset.id_translations]}
    if recipe.provenance.get('linearQcUnnormalized'):
        # CV and abundance after VSN read the unnormalized data (VSN is not linear).
        config['normalization'] = 'none'
    original_filename = recipe.original_filename
    raw = annotation.source_data
    collapse = kind == 'phosprot' and annotation.phosprot_lineage is not None
    if collapse:
        lineage = annotation.phosprot_lineage
        upstream_annotation, upstream_dataset = get_annotation('phospho'), get_current_dataset('phospho')
        if upstream_annotation is None or upstream_dataset is None:
            raise NotebookProvenanceError('The original phosphosite upload is needed to replay this collapse.')
        if upstream_dataset.id_translations and not upstream_annotation.source_data.equals(upstream_dataset.frame):
            raise NotebookProvenanceError('Upstream identifier translation is newer than its annotation.')
        config.update(aggregation=lineage.aggregation,
            upstream_metadata=upstream_annotation.metadata[['sample', 'condition']].to_dict(orient='records'),
            upstream={'kind': 'phospho', 'source': 'data' if lineage.source == 'log2' else lineage.source,
                'is_log2': upstream_annotation.is_log2_transformed, 'normalization': lineage.filter.normalization,
                'filter': lineage.filter.model_dump(), 'localization_cutoff': lineage.localizationCutoff,
                'linear_output': False,
                'id_translations': [step.model_dump() for step in upstream_dataset.id_translations]})
        raw = upstream_annotation.source_data
        original_filename = upstream_dataset.filename
    processing_metadata = annotation.metadata[['sample', 'condition']].copy()

    def finish():
        vsn = config['normalization'] == 'vsn' and source in {'data', 'filtered'}
        if collapse:
            vsn = vsn or config['upstream']['normalization'] == 'vsn'
        if vsn:
            runtime = vsn_runtime_version()
            config['vsn_runtime'] = runtime
            if collapse and config['upstream']['normalization'] == 'vsn':
                config['upstream']['vsn_runtime'] = runtime
        preprocessing = preprocessing_source(collapse, vsn)
        module = ModuleType('_copylot_preprocessing_validation')
        exec(preprocessing.code, module.__dict__)
        expected = pd.read_parquet(io.BytesIO(recipe.resources['input.parquet']))
        replay_function = 'replay_collapsed_input' if collapse else 'replay_preprocessing'
        # Annotation inputs already contain ID translations. The notebook's file does not.
        validation_config = {**config, 'id_translations': []} if not collapse else {
            **config, 'upstream': {**config['upstream'], 'id_translations': []}}
        replayed = getattr(module, replay_function)(raw, processing_metadata, validation_config)
        try:
            projected = replayed.loc[expected.index, expected.columns]
            pd.testing.assert_frame_equal(projected, expected, check_exact=True)
        except (AssertionError, KeyError) as exc:
            raise NotebookProvenanceError('Recorded preprocessing does not reproduce this plot input; regenerate annotations.') from exc
        merged = extract_notebook_source(_merge_source(recipe.source.code, preprocessing.code),
            tuple(dict.fromkeys((*recipe.source.functions, 'read_original_table', replay_function))))
        resources = {**recipe.resources,
            'processing_metadata.parquet': dataframe_bytes(processing_metadata),
            'processing.json': json.dumps(config, allow_nan=False).encode()}
        runtime_note = ''
        if vsn:
            r_version, vsn_version = runtime.split('|')
            runtime_note = f' Install R {r_version} and Bioconductor vsn {vsn_version}, with Rscript on PATH; these versions are checked before normalization.'
        projection_note = (' The displayed projection coordinates and cluster labels are retained for exact '
            'orientation; the plotting code reuses them after verifying the rebuilt analysis matrix.'
            if recipe.provenance.get('plot') == 'pca' else '')
        return replace(recipe, source=merged, resources=resources, original_filename=original_filename,
            provenance={**recipe.provenance, 'inputReplay': 'original-file', 'preprocessing': config},
            input_explanation='Set data_path to the original upload below. The notebook reads that file and repeats '
                'the recorded identifier translations, scale handling, normalization, filtering and localization selection required by this plot. '
                'Captured plot rows/columns define the view being reproduced. The exported input matrix is a verification '
                'reference only: it is never substituted for the original-file calculation.' + runtime_note + projection_note,
            preparation="raw = functions.read_original_table(data_path)\n"
                "processing_metadata = pd.read_parquet(RESOURCES / 'processing_metadata.parquet')\n"
                "processing = json.loads((RESOURCES / 'processing.json').read_text(encoding='utf-8'))\n"
                f"data = functions.{replay_function}(raw, processing_metadata, processing)\n"
                "reference = pd.read_parquet(RESOURCES / 'input.parquet')\n"
                "data = data.loc[reference.index, reference.columns]\n"
                "pd.testing.assert_frame_equal(data, reference, check_exact=True)\n")

    return RetainedReplay(finish, (raw, processing_metadata))
