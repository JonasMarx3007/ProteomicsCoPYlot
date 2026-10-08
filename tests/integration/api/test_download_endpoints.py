from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


DOWNLOADS = [
    "/api/annotations/current/protein/source/download",
    "/api/annotations/current/protein/filtered/download",
    "/api/annotations/current/protein/metadata/download",
]


def _rows(response) -> list[list[str]]:
    text = response.content.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text), delimiter="\t" if "\t" in text.split("\n")[0] else ","))


@pytest.mark.parametrize("path", DOWNLOADS)
def test_a_download_returns_a_parsable_table(client, path: str) -> None:
    """A downloaded table is the artefact that leaves the tool.

    Whatever a reviewer or collaborator checks, they check this file -- so it has
    to parse, carry a header, and hold rows.
    """
    response = client.get(path)
    assert response.status_code == 200, response.text[:200]
    rows = _rows(response)
    assert len(rows) >= 2, f"{path} returned {len(rows)} lines"
    assert rows[0], "the file has no header"
    assert len(rows[1]) == len(rows[0]), "the first data row does not match the header width"


@pytest.mark.parametrize("path", DOWNLOADS)
def test_a_download_is_offered_as_a_named_file(client, path: str) -> None:
    response = client.get(path)
    disposition = response.headers.get("content-disposition", "")
    assert "attachment" in disposition.lower(), f"{path} sent {disposition!r}"
    assert "filename" in disposition.lower(), f"{path} named no file: {disposition!r}"


def test_the_filtered_download_reflects_the_filter_not_the_source(client) -> None:
    """The two differ, or one of them is mislabelled."""
    source = _rows(client.get("/api/annotations/current/protein/source/download"))
    filtered = _rows(client.get("/api/annotations/current/protein/filtered/download"))
    assert len(filtered) <= len(source), (
        f"the filtered table has {len(filtered)} lines against the source's {len(source)}"
    )


def test_the_metadata_download_names_every_sample(client) -> None:
    rows = _rows(client.get("/api/annotations/current/protein/metadata/download"))
    header = [column.strip().lower() for column in rows[0]]
    assert "sample" in header and "condition" in header, header
    samples = [row[header.index("sample")] for row in rows[1:] if row]
    assert len(samples) == len(set(samples)), "the exported metadata repeats a sample"


@pytest.mark.parametrize("path", DOWNLOADS)
def test_an_unknown_kind_is_refused_by_a_download(client, path: str) -> None:
    response = client.get(path.replace("/protein/", "/NOT_A_KIND/"))
    assert response.status_code == 422, response.text[:160]
