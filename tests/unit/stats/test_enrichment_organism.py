"""The organism is a request parameter, and a wrong one is refused.

The bundled Gene Ontology table is human. That was a constant in the service,
stamped onto every result, which meant the result *reported* an organism nobody
had chosen and the tool had no place to put a second one.

It is now a request parameter with one accepted value. That is not decoration:
it makes adding a second organism a row in `GO_DATABASES` plus its table rather
than a new code path, and -- more importantly -- it makes an unrecognised
organism a refusal. Silently falling back to human is the one failure an
enrichment result cannot survive, because every number would be real and the
species would be wrong.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

from app.schemas.stats import EnrichmentRequest, ListEnrichmentRequest
from app.services.stats_tools import (
    GO_DATABASE_ORGANISM,
    GO_DATABASES,
    resolve_enrichment_organism,
)


def test_human_is_what_the_bundled_database_is() -> None:
    assert resolve_enrichment_organism("human") == GO_DATABASE_ORGANISM
    assert GO_DATABASES["human"] == "Homo sapiens"


def test_the_default_is_human_so_an_older_caller_is_unaffected() -> None:
    assert resolve_enrichment_organism() == GO_DATABASE_ORGANISM
    assert EnrichmentRequest(kind="protein").organism == "human"
    assert ListEnrichmentRequest().organism == "human"


@pytest.mark.parametrize("given", ["Human", " HUMAN ", "human"])
def test_the_key_is_read_case_and_space_insensitively(given: str) -> None:
    assert resolve_enrichment_organism(given) == GO_DATABASE_ORGANISM


@pytest.mark.parametrize("given", ["mouse", "Mus musculus", "yeast", "", "  "])
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
        resolve_enrichment_organism("mouse")
    assert "human" in str(excinfo.value)


def test_the_schema_refuses_an_unknown_organism_before_the_service_sees_it() -> None:
    """`Literal` means a bad value is a 422 with the accepted list in it."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        EnrichmentRequest(kind="protein", organism="mouse")
    with pytest.raises(ValidationError):
        ListEnrichmentRequest(organism="mouse")


def test_every_accepted_key_has_a_database_behind_it() -> None:
    """The Literal and the table are two lists of the same thing; they must agree."""
    from typing import get_args

    from app.schemas.stats import EnrichmentOrganism

    assert set(get_args(EnrichmentOrganism)) == set(GO_DATABASES)
