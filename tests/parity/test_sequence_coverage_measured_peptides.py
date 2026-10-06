"""Sequence coverage counts only peptides that were measured.

A peptide report lists precursors in runs where they were not quantified. A
peptide with no quantity above 0 in any run was not observed, so it no longer
covers sequence -- in the web app, the pip package and the R package alike.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from proteomicscopylot import notebook_functions as notebook

ROOT = Path(__file__).resolve().parents[2]

from app.services import peptide_tools  # noqa: E402

SEQUENCE = "MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQAPILSRVGDGTQDNLSGAEKAVQVKVK"  # 60 residues


def _db() -> pd.DataFrame:
    return pd.DataFrame({"full_header": ["sp|P00001|PROT1_HUMAN"], "V1": [SEQUENCE],
                         "name": ["PROT1_HUMAN"], "accession": ["P00001"]})


def _frame() -> pd.DataFrame:
    rows = [
        ("MKTAYIAK", "run1", 10.0), ("MKTAYIAK", "run2", np.nan),   # measured once: counts
        ("QISFVK", "run1", np.nan), ("QISFVK", "run2", 0.0),        # never measured: does not
        ("SHFSR", "run1", np.nan), ("SHFSR", "run2", np.nan),       # never measured: does not
        ("AVQVK", "run2", 3.0),                                     # measured: counts
    ]
    return pd.DataFrame({"ProteinNames": "PROT1_HUMAN", "Stripped.Sequence": [r[0] for r in rows],
                         "File.Name": [r[1] for r in rows], "Precursor.Quantity": [r[2] for r in rows]})


EXPECTED = round((8 + 5) / 60 * 100, 2)


def test_web_app_counts_only_measured_peptides(monkeypatch):
    monkeypatch.setattr(peptide_tools, "get_peptide_frame", _frame)
    monkeypatch.setattr(peptide_tools, "_load_fasta_dataframe", lambda species: _db())
    result = peptide_tools.peptide_sequence_coverage(species="human", protein="PROT1_HUMAN")
    assert result["coveragePercent"] == EXPECTED
    assert result["matchingPeptideCount"] == 2


def test_pip_counts_only_measured_peptides(tmp_path):
    path = tmp_path / "peptides.tsv"
    _frame().to_csv(path, sep="\t", index=False)
    assert notebook.calculate_coverage(str(path), _db(), "PROT1_HUMAN") == EXPECTED
    peptide_rows = [line for line in notebook.vis_coverage(_frame(), _db(), "PROT1_HUMAN").splitlines() if "-" in line]
    assert any("MKTAYIAK" in line.replace(" ", "") for line in peptide_rows)
    assert not any("QISFVK" in line.replace(" ", "") for line in peptide_rows)


@pytest.mark.requires_r()
def test_r_counts_only_measured_peptides(tmp_path):
    from app.services.r_runtime import detect_r_runtime

    runtime = detect_r_runtime()
    path = tmp_path / "peptides.tsv"
    _frame().to_csv(path, sep="\t", index=False)
    _db().to_csv(tmp_path / "db.csv", index=False)
    script = f"""
    suppressPackageStartupMessages(source("{(ROOT / 'proteomicscopylot' / 'notebook_functions.R').as_posix()}"))
    db <- read.csv("{(tmp_path / 'db.csv').as_posix()}", stringsAsFactors = FALSE)
    cat(calculate_coverage("{path.as_posix()}", db, "PROT1_HUMAN"))
    """
    completed = subprocess.run([str(runtime["executable"]), "-e", script], capture_output=True, text=True, timeout=300)
    assert completed.returncode == 0, completed.stderr[-2000:]
    assert float(completed.stdout.strip().splitlines()[-1]) == pytest.approx(EXPECTED)
