"""The organism is a request parameter, and a wrong one is refused.

The bundled Gene Ontology tables are human and mouse. The organism used to be a
constant in the service, stamped onto every result, which meant the result
*reported* an organism nobody had chosen and the tool had no place to put a
second one.

It is now a request parameter with one accepted value per bundled table. That
is not decoration: it makes adding an organism a row in `GO_DATABASES` plus its
table rather than a new code path, and -- more importantly -- it makes an
unrecognised organism a refusal. Silently falling back to human is the one
failure an enrichment result cannot survive, because every number would be real
and the species would be wrong.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

from app.schemas.stats import EnrichmentRequest, ListEnrichmentRequest
from app.services.stats_tools import (
    GO_DATABASE_ORGANISM,
    GO_DATABASES,
    load_go_db,
    pathway_options,
    resolve_enrichment_organism,
    run_enrichment_from_list,
)


def test_human_is_what_the_default_database_is() -> None:
    assert resolve_enrichment_organism("human") == GO_DATABASE_ORGANISM
    assert GO_DATABASES["human"] == ("Homo sapiens", "all_go_terms_genes.csv")
    assert GO_DATABASES["mouse"] == ("Mus musculus", "all_go_terms_genes_mouse.csv")


def test_the_default_is_human_so_an_older_caller_is_unaffected() -> None:
    assert resolve_enrichment_organism() == GO_DATABASE_ORGANISM
    assert EnrichmentRequest(kind="protein").organism == "human"
    assert ListEnrichmentRequest().organism == "human"


@pytest.mark.parametrize("given", ["Human", " HUMAN ", "human"])
def test_the_key_is_read_case_and_space_insensitively(given: str) -> None:
    assert resolve_enrichment_organism(given) == GO_DATABASE_ORGANISM


def test_mouse_is_its_own_database_not_a_relabelled_human_one() -> None:
    assert resolve_enrichment_organism("mouse") == "Mus musculus"
    human, mouse = load_go_db("human"), load_go_db("mouse")
    assert human.attrs["organism"] == "human" and mouse.attrs["organism"] == "mouse"
    human_genes = set(";".join(human["genes"].astype(str)).split(";"))
    mouse_genes = set(";".join(mouse["genes"].astype(str)).split(";"))
    # Mouse symbols are capitalised (Trp53), human ones upper-case (TP53).
    assert "TP53" in human_genes and "TP53" not in mouse_genes
    assert "Trp53" in mouse_genes and "Trp53" not in human_genes


@pytest.mark.parametrize("given", ["Mus musculus", "yeast", "rat", "", "  "])
def test_an_organism_with_no_bundled_database_is_refused(given: str) -> None:
    """Except the empty string, which means "unspecified" and takes the default."""
    if not given.strip():
        assert resolve_enrichment_organism(given) == GO_DATABASE_ORGANISM
        return
    with pytest.raises(ValueError, match="No Gene Ontology database is bundled"):
        resolve_enrichment_organism(given)


def test_the_refusal_names_what_is_available() -> None:
    """A refusal that does not say what to ask for instead is a dead end."""
    with pytest.raises(ValueError) as excinfo:
        resolve_enrichment_organism("yeast")
    assert "human" in str(excinfo.value) and "mouse" in str(excinfo.value)


def test_the_schema_refuses_an_unknown_organism_before_the_service_sees_it() -> None:
    """`Literal` means a bad value is a 422 with the accepted list in it."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        EnrichmentRequest(kind="protein", organism="yeast")
    with pytest.raises(ValidationError):
        ListEnrichmentRequest(organism="yeast")


def test_every_accepted_key_has_a_database_behind_it() -> None:
    """The Literal and the table are two lists of the same thing; they must agree."""
    from typing import get_args

    from app.schemas.stats import EnrichmentOrganism

    assert set(get_args(EnrichmentOrganism)) == set(GO_DATABASES)
    for key in GO_DATABASES:
        assert not load_go_db(key).empty


def test_pathway_options_follow_the_organism() -> None:
    human = set(pathway_options("human").pathways)
    mouse = set(pathway_options("mouse").pathways)
    assert human and mouse and human != mouse
    assert "apoptotic process" in human and "apoptotic process" in mouse


def test_a_mouse_gene_list_is_scored_against_the_mouse_table() -> None:
    """Mouse symbols against the human table would match nothing and warn; against
    the mouse table they are an ordinary query."""
    db = load_go_db("mouse")
    row = db.loc[db["description"] == "apoptotic process"].iloc[0]
    genes = sorted({gene for gene in str(row["genes"]).split(";") if gene})[:80]
    request = ListEnrichmentRequest(
        genes=genes, backgroundMode="global", organism="mouse", minTermSize=5, maxTermSize=5000,
        adjPValueCutoff=1.0,
    )
    result = run_enrichment_from_list(request)
    assert result.organism == "Mus musculus"
    assert result.terms
    assert not any("overlap" in warning.lower() for warning in result.warnings)

    human = run_enrichment_from_list(request.model_copy(update={"organism": "human"}))
    assert human.organism == "Homo sapiens"
    assert any("organism" in warning.lower() for warning in human.warnings)
