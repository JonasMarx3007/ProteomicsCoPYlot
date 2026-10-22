"""Every engine's accession column lands in `ProteinAccessions`.

A phosphosite is matched to its protein by accession, never by ProteinNames
(Spectronaut's PG.ProteinNames holds entry names). The column is collected at
upload like GeneNames and only missed by the tools that need it.
"""
import pandas as pd

from app.services.dataset_reader import rename_cols


def _renamed(**columns):
    return rename_cols(pd.DataFrame({name: ["x"] for name in columns.values()}))


def test_each_engines_accession_column_is_aliased() -> None:
    assert "ProteinAccessions" in rename_cols(pd.DataFrame({"PG.ProteinAccessions": ["P1"], "PG.ProteinNames": ["N_HUMAN"]}))
    diann = rename_cols(pd.DataFrame({"Protein.Group": ["P1"], "Protein.Ids": ["P1;P2"]}))
    assert list(diann["ProteinAccessions"]) == ["P1"] and list(diann["ProteinNames"]) == ["P1;P2"]
    assert "ProteinAccessions" in rename_cols(pd.DataFrame({"Protein ID": ["P1"], "Protein": ["sp|P1|X"]}))
    assert "ProteinAccessions" in rename_cols(pd.DataFrame({"Majority protein IDs": ["P1"], "Protein IDs": ["P1"]}))


def test_diann_protein_ids_serve_as_accessions_when_nothing_else_does() -> None:
    frame = rename_cols(pd.DataFrame({"Protein.Ids": ["P1;P2"]}))
    assert list(frame["ProteinNames"]) == ["P1;P2"] and list(frame["ProteinAccessions"]) == ["P1;P2"]


def test_the_phosphosite_protein_group_column_keeps_its_name() -> None:
    frame = rename_cols(pd.DataFrame({"PTM_Collapse_key": ["P1~G_S1_M1"], "Protein_group": ["P1"]}))
    assert "Protein_group" in frame.columns and "ProteinAccessions" not in frame.columns


def test_spectronaut_entry_names_never_become_accessions() -> None:
    frame = rename_cols(pd.DataFrame({"PG.ProteinNames": ["TMA7_HUMAN"], "PG.Genes": ["TMA7"]}))
    assert "ProteinAccessions" not in frame.columns
