"""Kinase Library motif windows are read from the protein, not the peptide.

The Kinase Library reads "_" as "beyond the protein terminus". A window cut from
the peptide alone padded every uncovered flank with "_": on the bundled HEK293
data 54% of windows were cut on the left, 37% on the right, and 27% lost the -3
position -- where basophilic R-x-x-S/T motifs sit, and exactly what tryptic
cleavage after R/K removes. Windows now come from the reference proteome at the
position in PTM_Collapse_key, with the peptide window as a reported fallback.
The backend and the pip package must build identical windows.
"""
from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd
import pytest

from app.services import phospho_tools
from proteomicscopylot import notebook_functions as notebook

REPO = Path(__file__).resolve().parents[3]
EXAMPLE_PP = REPO / "proteomicscopylot" / "example_data" / "20260511_144129_20240822_JM_HEK293_PP_Report_collapsed.tsv"
HUMAN_FASTA = REPO / "data" / "db" / "UP000005640_9606.fasta"

#                    1234567890123456789012345
PROTEIN = {"P1": "MKRRASLDEFGHIKLMNPQRSTVWY", "P2": "MSTY"}

CASES = [
    # R-x-x-S kept at -3 although the peptide starts at the A before the site.
    # S6 has five residues before it (MKRRA): two "_" for the protein start.
    ("P1~GENE_S6_M1", "As*LDEFGHIK", "__MKRRASLDEFGHI", "protein"),
    # N-terminal site: "_" only for positions before residue 1.
    ("P2~G2_S2_M1", "Ms*TY", "______MSTY_____", "protein"),
    # accession not in the proteome -> peptide fallback.
    ("P9~G9_S6_M1", "As*LDE", "______ASLDE____", "peptide"),
    # residue at that position is not the modified one -> fallback.
    ("P1~GENE_T6_M1", "At*LDE", "______ATLDE____", "peptide"),
    # peptide disagrees with the protein at a covered position -> fallback.
    ("P1~GENE_S6_M1", "Xs*LDE", "______XSLDE____", "peptide"),
    # the second accession of a group is used when the first does not fit.
    ("P9;P1~GENE_S6_M2", "As*LDE", "__MKRRASLDEFGHI", "protein"),
    # unparseable key -> fallback, no provenance.
    ("site-0", "As*LDE", "______ASLDE____", "peptide"),
]


@pytest.mark.parametrize("key,peptide,expected,source", CASES)
def test_backend_and_package_build_the_same_window(key, peptide, expected, source):
    backend = phospho_tools.site_motif_window(key, peptide, PROTEIN)
    package = notebook.site_motif_window(key, peptide, PROTEIN)
    assert backend == package
    assert backend["UPD_seq"] == expected
    assert backend["window_source"] == source
    assert len(backend["UPD_seq"]) == 15


def test_provenance_columns_name_the_site():
    row = phospho_tools.site_motif_window("P9;P1~GENE_S6_M2", "As*LDE", PROTEIN)
    assert (row["Protein"], row["Gene"], row["Site"]) == ("P1", "GENE", "S6")


def test_unknown_organism_is_rejected():
    with pytest.raises(ValueError, match="Unsupported organism"):
        phospho_tools._resolve_ksea_organism("zebrafish")


def test_package_warns_without_fasta_and_reads_one_when_given(tmp_path):
    fasta = tmp_path / "tiny.fasta"
    fasta.write_text(">sp|P1|ONE_HUMAN test\nMKRRASLDEF\nGHIKLMNPQRSTVWY\n>tr|P2|TWO\nMSTY\n")
    assert notebook.read_fasta(fasta) == PROTEIN
    samples = [f"{group}{i}" for group in "AB" for i in range(3)]
    meta = pd.DataFrame({"sample": samples, "condition": [s[0] for s in samples]})
    data = pd.DataFrame(
        [[1.0, 1.1, 0.9, 2.0, 2.1, 1.9], [1.0, 1.2, 0.8, 1.0, 1.1, 0.9]], columns=samples
    )
    data.insert(0, "UPD_seq", ["As*LDEFG", "Ms*TY"])
    data.insert(0, "PTM_Collapse_key", ["P1~GENE_S6_M1", "P2~G2_S2_M1"])
    with pytest.warns(UserWarning, match="No FASTA given"):
        bare = notebook.ksea_data_f(data, meta, "A", "B", in_log2fc=0)
    assert set(bare["window_source"]) == {"peptide"}
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        read = notebook.ksea_data_f(data, meta, "A", "B", in_log2fc=0, fasta=fasta)
    assert read["UPD_seq"].tolist() == ["__MKRRASLDEFGHI", "______MSTY_____"]
    assert read["PTM_Collapse_key"].tolist() == ["P1~GENE_S6_M1", "P2~G2_S2_M1"]
    assert read["log2FC"].tolist() == bare["log2FC"].tolist()


@pytest.mark.slow
def test_example_windows_come_from_the_protein():
    data = pd.read_csv(EXAMPLE_PP, sep="\t")
    sequences = notebook.read_fasta(HUMAN_FASTA)
    windows = [
        phospho_tools.site_motif_window(key, peptide, sequences)
        for key, peptide in zip(data["PTM_Collapse_key"], data["UPD_seq"])
    ]
    frame = pd.DataFrame(windows)
    assert (frame["window_source"] == "protein").mean() > 0.99
    protein = frame.loc[frame["window_source"] == "protein", "UPD_seq"]
    # "_" left in a protein window can only mean a real terminus: rare.
    assert (protein.str[4] == "_").mean() < 0.01
    # The centre is always the modified residue.
    keys = data.loc[frame["window_source"] == "protein", "PTM_Collapse_key"]
    residues = keys.str.extract(r"_([STY])\d+_M\d+$")[0]
    assert (protein.str[7].to_numpy() == residues.to_numpy()).all()
