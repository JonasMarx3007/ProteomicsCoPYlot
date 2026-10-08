"""Uploads that will mislead a reader now say so at annotation.

A long-format DIA-NN report taken for a protein table, an identifier that
occurs on several rows, and MaxQuant decoy/contaminant rows all used to pass
in silence. Nothing is removed; the annotation warning names what is there.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.annotation_processor import _table_shape_warnings, compute_annotation_from_metadata

SAMPLES = ["A1", "A2", "B1", "B2"]


def _protein_table(rows: int = 8) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    frame = pd.DataFrame({"ProteinNames": [f"P{i}" for i in range(rows)]})
    for sample in SAMPLES:
        frame[sample] = rng.normal(20, 1, rows)
    return frame


def test_a_clean_matrix_raises_no_shape_warning() -> None:
    assert _table_shape_warnings(_protein_table()) == []


def test_duplicate_identifiers_are_counted_and_kept() -> None:
    frame = _protein_table()
    frame.loc[3, "ProteinNames"] = "P1"
    frame.loc[5, "ProteinNames"] = "P1"
    warnings = _table_shape_warnings(frame)
    assert len(warnings) == 1 and warnings[0].startswith("2 rows repeat a ProteinNames")


def test_maxquant_decoys_and_contaminants_are_counted() -> None:
    frame = _protein_table()
    frame.loc[0, "ProteinNames"] = "REV__P0"
    frame.loc[1, "ProteinNames"] = "CON__P1"
    frame["Reverse"] = ["", "", "+", "", "", "", "", ""]
    frame["Potential contaminant"] = ["", "", "", "+", "", "", "", ""]
    warnings = _table_shape_warnings(frame)
    assert any(w.startswith("4 rows look like decoy or contaminant entries") for w in warnings)


def test_a_long_format_report_is_recognised() -> None:
    # DIA-NN report.tsv: one row per precursor and run.
    rows = []
    for run in ["run1", "run2", "run3"]:
        for protein in ["P1", "P2", "P3"]:
            for precursor in ("a", "b"):
                rows.append({"Run": run, "ProteinNames": protein, "Precursor.Id": f"{protein}{precursor}",
                             "PG.Quantity": 1e6, "Precursor.Quantity": 1e5})
    frame = pd.DataFrame(rows)
    warnings = _table_shape_warnings(frame)
    assert len(warnings) == 1
    assert "long-format precursor or peptide report" in warnings[0] and "Peptide page" in warnings[0]


def test_overlapping_flags_count_each_row_only_once() -> None:
    frame = _protein_table()
    frame.loc[0, "ProteinNames"] = "REV__P0"
    frame["Reverse"] = ["+"] + [""] * 7
    frame["Potential contaminant"] = ["+"] + [""] * 7
    frame["Only identified by site"] = ["+"] + [""] * 7
    assert any(w.startswith("1 rows look like") for w in _table_shape_warnings(frame))


def test_the_warnings_reach_the_annotation() -> None:
    frame = _protein_table()
    frame.loc[3, "ProteinNames"] = "P1"
    metadata = pd.DataFrame({"sample": SAMPLES, "condition": ["A", "A", "B", "B"]})
    computed = compute_annotation_from_metadata(
        data=frame, metadata=metadata, is_log2_transformed=True, min_present=1, filter_mode="per_group",
    )
    assert any("rows repeat a ProteinNames" in w for w in computed.warnings)
    assert len(computed.filtered_data) == 8  # kept
