"""A search database names isoforms and non-canonical entries that the canonical reference
proteome FASTA does not carry: 'A0A140T8R7' (a mouse Rcor1 isoform) failed with "does not exist
in the loaded database" (2026-10-14). The release's "additional" file, logged in the manifest,
is consulted on a miss; a species mix-up is named.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from app.services import peptide_tools

ROOT = Path(__file__).resolve().parents[3]


def _frame(protein: str, peptides: list[str]) -> pd.DataFrame:
    return pd.DataFrame({"ProteinNames": [protein] * len(peptides), "Stripped.Sequence": peptides,
                         "File.Name": ["run1"] * len(peptides), "Precursor.Quantity": [1.0] * len(peptides)})


def test_the_additional_fasta_files_are_bundled_and_logged() -> None:
    manifest = json.loads((ROOT / "data" / "reference-sources" / "manifest.json").read_text(encoding="utf-8"))
    for key, name in (("uniprot_human_proteome_fasta_additional", "UP000005640_9606_additional.fasta.gz"),
                      ("uniprot_mouse_proteome_fasta_additional", "UP000000589_10090_additional.fasta.gz")):
        source = manifest["sources"][key]
        assert source["file"] == name and source["release"] and source["retrieved"] and source["sha256"] and source["url"].startswith("https://ftp.uniprot.org/")
        assert manifest["outputs"][name]["sha256"] == source["sha256"]
        assert manifest["build"]["sources_sha256"][key] == source["sha256"]
        assert (ROOT / "data" / "db" / name).is_file()
    log = (ROOT / "data" / "db" / "BUILD.log").read_text(encoding="utf-8")
    assert "UP000000589_10090_additional.fasta.gz" in log and "UP000005640_9606_additional.fasta.gz" in log


def test_a_non_canonical_entry_is_found_in_the_additional_file(monkeypatch) -> None:
    additional = peptide_tools._load_additional_fasta_dataframe("mouse")
    assert additional is not None
    sequence = peptide_tools._fasta_sequence(peptide_tools._load_fasta_dataframe("mouse"), "A0A140T8R7", "mouse")
    assert sequence is not None and len(sequence) == 382  # UniProt: isoform of Q8CFE3, REST corepressor 1
    peptide = sequence[10:22]
    monkeypatch.setattr(peptide_tools, "get_peptide_frame", lambda: _frame("A0A140T8R7", [peptide]))
    result = peptide_tools.peptide_sequence_coverage(species="mouse", protein="A0A140T8R7")
    assert result["matchingPeptideCount"] == 1 and result["warnings"] == []


def test_a_mouse_entry_asked_as_human_names_the_species(monkeypatch) -> None:
    monkeypatch.setattr(peptide_tools, "get_peptide_frame", lambda: _frame("A0A140T8R7", ["PEPTIDEK"]))
    with pytest.raises(ValueError, match="is in the mouse one. Select mouse as the species"):
        peptide_tools.peptide_sequence_coverage(species="human", protein="A0A140T8R7")


def test_an_unknown_entry_names_both_parts_of_the_database(monkeypatch) -> None:
    monkeypatch.setattr(peptide_tools, "get_peptide_frame", lambda: _frame("NOPE_NOTAPROTEIN", ["PEPTIDEK"]))
    with pytest.raises(ValueError, match="loaded human database \\(UniProt reference proteome, canonical and additional entries\\)"):
        peptide_tools.peptide_sequence_coverage(species="human", protein="NOPE_NOTAPROTEIN")
