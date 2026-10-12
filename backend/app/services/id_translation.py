from __future__ import annotations

import logging

import io
import hashlib
import json
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

import pandas as pd

from app.schemas.annotation import AnnotationKind
from app.schemas.data_tools import IdTranslationRequest, IdTranslationResponse
from app.services.dataset_store import get_current_dataset
from app.services.reference_db import resolve_reference_db
from app.services.dataset_store import save_table_dataset
from app.services.json_records import json_records

LOGGER = logging.getLogger(__name__)


UNIPROT_ALL_ACCESSIONS = "UniProt All Accessions"
VIRTUAL_COL_UNIPROT_ALL = "__uniprot_all_accessions__"

DB_TO_COL = {
    "HGNC ID": "hgnc_id",
    "HGNC Symbol": "symbol",
    "HGNC Name": "name",
    "HGNC Alias Symbol": "alias_symbol",
    "Ensembl": "ensembl_gene_id",
    "VEGA": "vega_id",
    "ENA": "ena",
    "RefSeq": "refseq_accession",
    "CCDS": "ccds_id",
    "PubMed": "pubmed_id",
    "Enzyme Commission (EC)": "enzyme_id",
    "RNAcentral": "rna_central_id",
    "UniProt Accession": "uniprot_symbol",
    "UniProt Name": "uniprot_name",
    "UniProt Gene": "uniprot_gene",
    "UniProt Description": "uniprot_description",
    "UniProt Secondary Accession": "uniprot_alternative",
    UNIPROT_ALL_ACCESSIONS: VIRTUAL_COL_UNIPROT_ALL,
    # Added with the 2026-10-12 rebuild of BioNamesDB (human + mouse; see
    # data/db/README.md). The HGNC columns are filled for human genes, the MGI
    # columns for mouse genes; Entrez and Ensembl for both.
    "Entrez Gene ID": "entrez_gene_id",
    "OMIM": "omim_id",
    "MGI ID": "mgi_id",
    "MGI Symbol": "mgi_symbol",
    "MGI Name": "mgi_name",
    "MGI Synonym": "mgi_synonym",
}

OUT_LABEL_TO_COLNAME = {
    "HGNC ID": "HGNCIDNames",
    "HGNC Symbol": "GeneNames",
    "HGNC Name": "HGNCNames",
    "HGNC Alias Symbol": "HGNCAliasSymbolNames",
    "Ensembl": "EnsemblNames",
    "VEGA": "VEGANames",
    "ENA": "ENANames",
    "RefSeq": "RefSeqNames",
    "CCDS": "CCDSNames",
    "PubMed": "PubMedNames",
    "Enzyme Commission (EC)": "ECNames",
    "RNAcentral": "RNAcentralNames",
    "UniProt Accession": "UniProtAccessionNames",
    "UniProt Name": "UniProtNames",
    "UniProt Gene": "GeneNames",
    "UniProt Description": "UniProtDescriptionNames",
    "UniProt Secondary Accession": "UniProtSecondaryAccessionNames",
    UNIPROT_ALL_ACCESSIONS: "UniProtAllAccessionsNames",
    "Entrez Gene ID": "EntrezGeneIDNames",
    "OMIM": "OMIMNames",
    "MGI ID": "MGIIDNames",
    "MGI Symbol": "MGISymbolNames",
    "MGI Name": "MGINames",
    "MGI Synonym": "MGISynonymNames",
}

SPLIT_SEMI = re.compile(r"\s*;\s*")


def available_database_labels() -> list[str]:
    return list(DB_TO_COL.keys())


def _preview(df: pd.DataFrame, rows: int = 50) -> list[dict[str, object]]:
    return json_records(df, rows)


def _get_current_frame(kind: AnnotationKind) -> tuple[pd.DataFrame, str]:
    current = get_current_dataset(kind)
    if current is None or not hasattr(current, "frame"):
        raise ValueError(f"No {kind} dataset is currently loaded.")
    return current.frame.copy(), current.filename


def resolve_bionamesdb_path() -> Path:
    return resolve_reference_db("BioNamesDB.txt.gz", "identifier database (BioNamesDB.txt.gz)")


@lru_cache(maxsize=1)
def load_db() -> pd.DataFrame:
    path = resolve_bionamesdb_path()
    return pd.read_csv(path, sep="\t", dtype=str, keep_default_na=False).replace("", pd.NA)


def split_cell_values(val: object) -> list[str]:
    if pd.isna(val):
        return []
    text = str(val).strip()
    if not text:
        return []
    parts = [part.strip() for part in SPLIT_SEMI.split(text) if part.strip()]
    seen: set[str] = set()
    result: list[str] = []
    for part in parts:
        if part not in seen:
            result.append(part)
            seen.add(part)
    return result


def _values_from_row(row: pd.Series, col_or_virtual: str) -> list[str]:
    if col_or_virtual == VIRTUAL_COL_UNIPROT_ALL:
        primary = split_cell_values(row.get("uniprot_symbol", pd.NA))
        secondary = split_cell_values(row.get("uniprot_alternative", pd.NA))
        seen: set[str] = set()
        result: list[str] = []
        for token in [*primary, *secondary]:
            if token not in seen:
                result.append(token)
                seen.add(token)
        return result
    return split_cell_values(row.get(col_or_virtual, pd.NA))


def translation_key(value):
    return hashlib.sha256(json.dumps(split_cell_values(value), ensure_ascii=True).encode()).hexdigest()


def replay_id_translations(frame, steps):
    if not steps:
        return frame
    frame = frame.copy()
    for step in steps:
        if step['sourceColumn'] not in frame:
            raise ValueError('The original file lacks the recorded identifier source column.')
        keys = frame[step['sourceColumn']].map(translation_key)
        for column, lookup in step['outputs'].items():
            if not keys.isin(lookup).all():
                raise ValueError('The original file contains identifiers outside the recorded translation.')
            frame.loc[:, column] = keys.map(lookup).tolist()
    return frame


def build_index(db_df: pd.DataFrame, in_label: str, out_label: str) -> dict[str, list[str]]:
    in_col = DB_TO_COL[in_label]
    out_col = DB_TO_COL[out_label]
    index: dict[str, set[str]] = defaultdict(set)
    for _, row in db_df.iterrows():
        in_values = _values_from_row(row, in_col)
        out_values = _values_from_row(row, out_col)
        if not in_values or not out_values:
            continue
        for in_value in in_values:
            for out_value in out_values:
                index[in_value].add(out_value)
    return {key: sorted(values) for key, values in index.items()}


def build_value_sets(db_df: pd.DataFrame, labels: tuple[str, ...]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for label in labels:
        col = DB_TO_COL[label]
        values: set[str] = set()
        if col == VIRTUAL_COL_UNIPROT_ALL:
            for source_col in ("uniprot_symbol", "uniprot_alternative"):
                if source_col not in db_df.columns:
                    continue
                for raw_value in db_df[source_col].dropna().astype(str):
                    values.update(split_cell_values(raw_value))
            out[label] = values
            continue
        if col not in db_df.columns:
            out[label] = set()
            continue
        for raw_value in db_df[col].dropna().astype(str):
            values.update(split_cell_values(raw_value))
        out[label] = values
    return out


def autodetect_input_db(ids: list[str], db_df: pd.DataFrame) -> str | None:
    labels = available_database_labels()
    value_sets = build_value_sets(db_df, tuple(labels))
    scores = {label: sum(1 for item in ids if item in value_sets.get(label, set())) for label in labels}
    best_score = max(scores.values()) if scores else 0
    if best_score <= 0:
        return None
    top_labels = [label for label, score in scores.items() if score == best_score]
    if UNIPROT_ALL_ACCESSIONS in top_labels:
        return UNIPROT_ALL_ACCESSIONS
    for label in labels:
        if scores.get(label, 0) == best_score:
            return label
    return None


def translate_cell(cell: object, index: dict[str, list[str]]) -> tuple[str, bool]:
    tokens = split_cell_values(cell)
    if not tokens:
        return "NA", False
    out_values: set[str] = set()
    for token in tokens:
        out_values.update(index.get(token, []))
    if not out_values:
        return "NA", False
    return ";".join(sorted(out_values)), True


def _translated_values(cells: list[object], index: dict[str, list[str]]) -> tuple[list[str], int]:
    values: list[str] = []
    translated_count = 0
    for cell in cells:
        value, ok = translate_cell(cell, index)
        values.append(value)
        if ok:
            translated_count += 1
    return values, translated_count


def translated_dataframe(payload: IdTranslationRequest) -> tuple[pd.DataFrame, str, str, str, list[str]]:
    if payload.outputDb not in DB_TO_COL:
        raise ValueError(f"Unsupported output database: {payload.outputDb}")

    frame, filename = _get_current_frame(payload.kind)
    if payload.column not in frame.columns:
        raise ValueError(f"Column '{payload.column}' was not found in the {payload.kind} dataset.")

    db_df = load_db()
    requested_input = payload.inputDb
    if requested_input is not None and requested_input not in DB_TO_COL:
        raise ValueError(f"Unsupported input database: {requested_input}")

    effective_input = requested_input
    warnings: list[str] = []
    if payload.autoDetectInput or not effective_input:
        sample_values = (
            frame[payload.column]
            .dropna()
            .astype(str)
            .map(str.strip)
            .loc[lambda series: series != ""]
            .head(5000)
            .tolist()
        )
        expanded: list[str] = []
        for value in sample_values:
            expanded.extend(split_cell_values(value))
        detected = autodetect_input_db(expanded[:20000], db_df) if expanded else None
        if detected is None and not effective_input:
            raise ValueError("Could not auto-detect the input database from the selected column.")
        if detected is not None:
            effective_input = detected
        elif requested_input:
            warnings.append("Auto-detection found no match, so the manually selected input database was used.")

    if effective_input is None:
        raise ValueError("An input database is required.")

    index = build_index(db_df, effective_input, payload.outputDb)
    output_column = OUT_LABEL_TO_COLNAME.get(payload.outputDb, payload.outputDb.replace(" ", "") + "Names")

    source_cells = frame[payload.column].tolist()
    translated_values, _ = _translated_values(source_cells, index)

    translated = frame.copy()
    translated.loc[:, output_column] = translated_values

    if "GeneNames" not in translated.columns and output_column != "GeneNames":
        gene_name_index = build_index(db_df, effective_input, "HGNC Symbol")
        gene_name_values, gene_name_hits = _translated_values(source_cells, gene_name_index)
        if gene_name_hits > 0:
            translated.loc[:, "GeneNames"] = gene_name_values
            warnings.append(
                "Added GeneNames column (HGNC Symbol) so downstream gene-name based analyses can run."
            )
    return translated, filename, effective_input, output_column, warnings


def _download_details(original_filename: str) -> tuple[str, str]:
    suffix = Path(original_filename).suffix.lower()
    stem = Path(original_filename).stem
    if suffix in {".tsv", ".txt"}:
        return f"{stem}_translated{suffix}", "text/tab-separated-values"
    return f"{stem}_translated.csv", "text/csv"


def run_id_translation(payload: IdTranslationRequest) -> IdTranslationResponse:
    from app.app_version import APP_VERSION
    from app.schemas.annotation import IdentifierTranslationStep
    current = get_current_dataset(payload.kind)
    translated, filename, input_db, output_column, warnings = translated_dataframe(payload)
    if get_current_dataset(payload.kind) is not current:
        raise ValueError('The dataset changed during identifier translation; try again.')
    columns = [output_column]
    if 'GeneNames' not in current.frame.columns and 'GeneNames' in translated and output_column != 'GeneNames':
        columns.append('GeneNames')
    keys = current.frame[payload.column].map(translation_key).tolist()
    step = IdentifierTranslationStep(sourceColumn=payload.column, inputDb=input_db,
        outputDb=payload.outputDb, toolVersion=APP_VERSION,
        outputs={column: dict(zip(keys, translated[column].tolist())) for column in columns})
    save_table_dataset(filename=filename, kind=payload.kind, frame=translated,
        phosprot_aggregation=current.phosprot_aggregation, phosprot_lineage=current.phosprot_lineage,
        id_translations=[*current.id_translations, step])
    download_filename, _ = _download_details(filename)
    persisted_warnings = list(warnings)
    persisted_warnings.append(
        f"Applied translated column(s) to active {payload.kind} dataset. Re-run annotation to propagate into filtered/log2 data."
    )
    return IdTranslationResponse(
        kind=payload.kind,
        sourceColumn=payload.column,
        outputColumn=output_column,
        inputDb=input_db,
        outputDb=payload.outputDb,
        translatedCount=int((translated[output_column] != "NA").sum()),
        totalRows=int(len(translated)),
        preview=_preview(translated),
        availableColumns=[str(col) for col in translated.columns],
        availableDatabases=available_database_labels(),
        downloadFilename=download_filename,
        warnings=persisted_warnings,
    )


def export_id_translation(payload: IdTranslationRequest) -> tuple[str, bytes, str]:
    translated, filename, _, _, _ = translated_dataframe(payload)
    download_filename, media_type = _download_details(filename)
    separator = "\t" if media_type == "text/tab-separated-values" else ","
    buffer = io.StringIO()
    translated.to_csv(buffer, index=False, sep=separator)
    return download_filename, buffer.getvalue().encode("utf-8"), media_type
