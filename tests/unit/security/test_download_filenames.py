"""Download names survive quotes, line breaks and non-ASCII characters.

They include names a user typed (packages, datasets, conditions). Written into
`filename="..."` unchanged, a quote ended the value early, a line break could
split the header, and a non-Latin-1 name could not be sent at all.
"""
from __future__ import annotations

from urllib.parse import unquote

import pytest

from app.api.download_headers import attachment_disposition


def _parts(header: str) -> dict[str, str]:
    out = {}
    for part in header.split(";")[1:]:
        key, _, value = part.strip().partition("=")
        out[key] = value
    return out


def test_a_plain_name_is_sent_as_before() -> None:
    assert attachment_disposition("copylot_Data_20261002.copylotstate") == (
        'attachment; filename="copylot_Data_20261002.copylotstate"'
    )


@pytest.mark.parametrize("name", ['Grüne Probe "1".csv', "数据.csv", "a\r\nSet-Cookie: x=1.csv", "WT;GRK.tsv"])
def test_any_name_keeps_one_header_line_and_round_trips(name: str) -> None:
    header = attachment_disposition(name)
    assert "\r" not in header and "\n" not in header
    header.encode("latin-1")  # must be sendable at all
    parts = _parts(header)
    ascii_name = parts["filename"]
    assert ascii_name.startswith('"') and ascii_name.endswith('"') and '"' not in ascii_name[1:-1]
    assert ascii_name.strip('"').rsplit(".", 1)[0].strip("_"), "the ASCII stand-in lost its stem"
    expected = name.replace("\r\n", " ")
    assert unquote(parts["filename*"].removeprefix("UTF-8''")) == expected


# --- the routes that pass a name through ------------------------------------------
#
# Two downloads are named after something the user chose: the identifier
# translation after the uploaded file, the notebook export after the plot. Each
# route is handed a hostile name by stubbing the service behind it, and the
# header that comes back over HTTP must be the one `attachment_disposition`
# builds -- one line, sendable, with the real name recoverable. A route that
# writes `filename="..."` itself fails on the quote and the line break.
#
# The other downloads (annotation tables, imputed matrix, saved state) are named
# from fixed ASCII parts; for those a hand-written header is byte-identical to
# the helper's, so there is no behaviour to tell them apart by.

HOSTILE = 'Grüne "Probe"\r\nSet-Cookie: x=1.csv'


def _assert_safe(response, name: str) -> None:
    assert response.status_code == 200, response.text[:200]
    header = response.headers["content-disposition"]
    assert "\r" not in header and "\n" not in header
    header.encode("latin-1")
    assert header == attachment_disposition(name), header
    assert unquote(_parts(header)["filename*"].removeprefix("UTF-8''")) == name.replace("\r\n", " ")


@pytest.fixture
def api():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app, base_url="http://localhost") as client:
        yield client


def test_the_translation_download_names_the_file_safely(api, monkeypatch) -> None:
    from app.api import routes_data_tools

    monkeypatch.setattr(routes_data_tools, "export_id_translation", lambda payload: (HOSTILE, b"id\n1\n", "text/csv"))
    response = api.post("/api/data-tools/id-translation/download",
                        json={"kind": "protein", "column": "ProteinNames", "outputDb": "uniprot"})
    _assert_safe(response, HOSTILE)


def test_the_notebook_download_names_the_file_safely(api, monkeypatch) -> None:
    from app.services import notebook_archive, notebook_qc

    name = HOSTILE.replace(".csv", ".zip")
    monkeypatch.setattr(notebook_qc.snapshots, "get", lambda session, token: object())
    monkeypatch.setattr(notebook_archive, "build_notebook_archive", lambda recipe: (name, b"PK"))
    response = api.get(f"/api/plots/notebooks/{'a' * 32}.zip")
    _assert_safe(response, name)
