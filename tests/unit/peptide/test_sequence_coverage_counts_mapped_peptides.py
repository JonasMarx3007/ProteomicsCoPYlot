"""Sequence coverage counts the peptides that occur in the selected sequence.

The coverage percentage was always built from those, but the peptide count
next to it counted every peptide the report assigns to the protein group --
including ones that do not occur in the chosen FASTA sequence (another
isoform or database entry, a sequence variant) -- and `warnings` was a
hard-coded empty list, so nothing on the page could explain the gap.
"""

from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import peptide_tools

# 60 residues; peptides are chosen so their positions are easy to count.
CANONICAL = "MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQAPILSRVGDGTQDNLSGAEKAVQVKVK"
ISOFORM = CANONICAL[:10] + "GGGGGGGGGG" + CANONICAL[10:]  # insertion between two peptides


def _db() -> pd.DataFrame:
    headers = ["sp|P00001|PROT1_HUMAN", "sp|P00001-2|PROT1_HUMAN"]
    frame = pd.DataFrame({"full_header": headers, "V1": [CANONICAL, ISOFORM]})
    frame["name"] = ["PROT1_HUMAN", "PROT1_HUMAN-2"]
    frame["accession"] = ["P00001", "P00001-2"]
    return frame


def _frame(peptides: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ProteinNames": ["PROT1_HUMAN"] * len(peptides),
            "Stripped.Sequence": peptides,
            "File.Name": ["run1"] * len(peptides),
            "Precursor.Quantity": [1.0] * len(peptides),
        }
    )


MAPPED = ["MKTAYIAK", "QISFVK", "SHFSR", "LGLIEVQAPILSR", "AVQVK"]  # 8+6+5+13+5 = 37 residues
UNMAPPED = "GGGGGGGGGG"  # only in the isoform


@pytest.fixture
def stubbed(monkeypatch):
    def install(peptides: list[str]):
        monkeypatch.setattr(peptide_tools, "get_peptide_frame", lambda: _frame(peptides))
        monkeypatch.setattr(peptide_tools, "_load_fasta_dataframe", lambda species: _db())

    return install


def test_the_count_is_the_mapped_peptides_and_the_gap_is_explained(stubbed):
    stubbed(MAPPED + [UNMAPPED])
    result = peptide_tools.peptide_sequence_coverage(species="human", protein="PROT1_HUMAN")
    assert result["assignedPeptideCount"] == 6
    assert result["matchingPeptideCount"] == 5
    assert result["unmappedPeptides"] == [UNMAPPED]
    assert result["coveragePercent"] == pytest.approx(37 / 60 * 100, abs=0.01)
    assert len(result["warnings"]) == 1
    assert result["warnings"][0].startswith(
        "1 of 6 peptides assigned to this protein group do not occur in the selected sequence (e.g. GGGGGGGGGG)"
    )
    assert "isoform" in result["warnings"][0]


def test_fully_mapped_peptides_raise_no_warning(stubbed):
    stubbed(MAPPED)
    result = peptide_tools.peptide_sequence_coverage(species="human", protein="PROT1_HUMAN")
    assert (result["matchingPeptideCount"], result["assignedPeptideCount"]) == (5, 5)
    assert result["unmappedPeptides"] == []
    assert result["warnings"] == []


def test_the_isoform_variant_maps_the_peptide_the_canonical_does_not(stubbed, monkeypatch):
    frame = _frame(MAPPED + [UNMAPPED])
    frame["ProteinNames"] = "PROT1_HUMAN-2"
    monkeypatch.setattr(peptide_tools, "get_peptide_frame", lambda: frame)
    monkeypatch.setattr(peptide_tools, "_load_fasta_dataframe", lambda species: _db())
    result = peptide_tools.peptide_sequence_coverage(species="human", protein="PROT1_HUMAN-2")
    assert result["matchingPeptideCount"] == 6
    assert result["warnings"] == []


def test_the_route_serves_the_new_fields(stubbed):
    stubbed(MAPPED + [UNMAPPED])
    with TestClient(app, base_url="http://localhost") as client:
        response = client.get(
            "/api/peptide/sequence-coverage", params={"species": "human", "protein": "PROT1_HUMAN"}
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["matchingPeptideCount"] == 5
    assert payload["assignedPeptideCount"] == 6
    assert payload["unmappedPeptides"] == [UNMAPPED]
    assert len(payload["warnings"]) == 1
