"""A FragPipe protein table is usable, and a table without an identifier says so.

FragPipe's combined_protein.tsv names its columns "Protein", "Protein ID",
"Gene" and "<run> MaxLFQ Intensity". "Protein" and "Gene" are now aliased to
ProteinNames and GeneNames at upload, as the Spectronaut/DIA-NN/MaxQuant names
already were. A table that still has no identifier column used to annotate in
silence and then fail on every statistics page with a 400 that did not say what
was missing; the annotation now warns, and the 400 names the accepted columns.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services.annotation_processor import compute_annotation_from_metadata
from app.services.dataset_reader import rename_cols
from app.services.stats_tools import _resolve_label_column

RUNS = ["A1", "A2", "A3", "B1", "B2", "B3"]


def _fragpipe() -> pd.DataFrame:
    rng = np.random.default_rng(2)
    frame = pd.DataFrame({
        "Protein": [f"sp|P{i:05d}|PROT{i}_HUMAN" for i in range(12)],
        "Protein ID": [f"P{i:05d}" for i in range(12)],
        "Entry Name": [f"PROT{i}_HUMAN" for i in range(12)],
        "Gene": [f"G{i}" for i in range(12)],
        "Protein Probability": [1.0] * 12,
        "Combined Total Peptides": [5] * 12,
    })
    for run in RUNS:
        frame[f"{run} Spectral Count"] = 5
        frame[f"{run} Intensity"] = np.power(2.0, rng.normal(22, 1, 12))
        frame[f"{run} MaxLFQ Intensity"] = np.power(2.0, rng.normal(22, 1, 12))
    return frame


def test_fragpipe_protein_and_gene_columns_are_aliased() -> None:
    renamed = rename_cols(_fragpipe())
    assert "ProteinNames" in renamed.columns and "GeneNames" in renamed.columns
    assert "ProteinAccessions" in renamed.columns  # the bare accession, for the protein correction
    assert _resolve_label_column("protein", "workflow", renamed) == "ProteinNames"
    assert _resolve_label_column("protein", "genes", renamed) == "GeneNames"


def test_a_table_without_an_identifier_column_is_annotated_with_a_warning() -> None:
    frame = _fragpipe().drop(columns=["Protein", "Gene"])  # nothing aliasable left
    renamed = rename_cols(frame)
    samples = [f"{run} MaxLFQ Intensity" for run in RUNS]
    metadata = pd.DataFrame({"sample": samples, "condition": ["A"] * 3 + ["B"] * 3})
    computed = compute_annotation_from_metadata(
        data=renamed, metadata=metadata, is_log2_transformed=False, min_present=1, filter_mode="per_group",
    )
    assert any("No identifier column was recognised" in w and "ProteinNames" in w for w in computed.warnings)
    assert len(computed.filtered_data) == 12  # the QC path still works


def test_the_statistics_error_names_the_accepted_columns() -> None:
    frame = _fragpipe().drop(columns=["Protein", "Gene"])
    with pytest.raises(ValueError, match="ProteinNames"):
        _resolve_label_column("protein", "workflow", rename_cols(frame))


def test_a_recognised_table_gets_no_identifier_warning() -> None:
    renamed = rename_cols(_fragpipe())
    samples = [f"{run} MaxLFQ Intensity" for run in RUNS]
    metadata = pd.DataFrame({"sample": samples, "condition": ["A"] * 3 + ["B"] * 3})
    computed = compute_annotation_from_metadata(
        data=renamed, metadata=metadata, is_log2_transformed=False, min_present=1, filter_mode="per_group",
    )
    assert not any("identifier column" in w for w in computed.warnings)
