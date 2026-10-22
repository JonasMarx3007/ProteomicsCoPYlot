"""An upload cannot name a server file, and an export never reads a non-file.

`POST /api/datasets/upload` accepted a
`sourcePath` form field and stored it unchecked as the dataset's source. The
next export fingerprinted that path, so a logged-in remote user of a protected
tool server got the size and SHA-256 of any file the container could read, and
`/dev/zero` held an export thread forever. No page ever sent the field; it is
gone, and the fingerprint now opens regular files only.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import restore_state
from app.services.password_hashing import hash_password

TABLE = b"ProteinNames,A1,A2,B1,B2\nP1,1,2,3,4\n"


@pytest.fixture
def remote_client(monkeypatch, tmp_path):
    access = tmp_path / "access.json"
    access.write_text(json.dumps({"password_pbkdf2_sha256": hash_password("upload-path-test")}))
    monkeypatch.setenv("COPYLOT_TOOL_ACCESS_ENABLED", "1")
    monkeypatch.setenv("COPYLOT_TOOL_ACCESS_FILE", str(access))
    monkeypatch.setenv("COPYLOT_SESSION_ISOLATION", "1")
    with TestClient(app, client=("198.51.100.10", 50000)) as client:
        assert client.post("/api/tool/auth/login", json={"password": "upload-path-test"}).status_code == 200
        yield client


def _exported_protein_entry(client: TestClient, *, portable: bool) -> dict:
    response = client.post("/api/restore/export", json={"portable": portable})
    assert response.status_code == 200, response.text
    state = json.loads(gzip.decompress(response.content))
    return next(
        p["datasets"]["protein"] for p in state["backend"]["packages"] if p["datasets"].get("protein")
    )


def test_a_supplied_source_path_is_ignored_and_never_fingerprinted(remote_client, tmp_path) -> None:
    secret = tmp_path / "server-secret.txt"
    secret.write_bytes(b"not for this user\n")
    secret_sha = hashlib.sha256(secret.read_bytes()).hexdigest()

    uploaded = remote_client.post(
        "/api/datasets/upload",
        data={"kind": "protein", "sourcePath": str(secret)},
        files={"file": ("table.csv", TABLE)},
    )
    assert uploaded.status_code == 200, uploaded.text
    stored = Path(uploaded.json()["sourcePath"])
    assert stored != secret
    assert stored.read_bytes() == TABLE, "the upload is the server's own copy of the sent bytes"

    for portable in (True, False):
        entry = _exported_protein_entry(remote_client, portable=portable)
        assert entry.get("sha256") != secret_sha
        assert entry.get("sha256") == hashlib.sha256(TABLE).hexdigest()
        assert str(secret) not in json.dumps(entry)


def test_the_upload_route_no_longer_declares_source_path() -> None:
    body = app.openapi()["paths"]["/api/datasets/upload"]["post"]["requestBody"]["content"]
    schema_ref = body["multipart/form-data"]["schema"]["$ref"].rsplit("/", 1)[-1]
    fields = app.openapi()["components"]["schemas"][schema_ref]["properties"]
    assert "sourcePath" not in fields


def test_only_regular_files_are_fingerprinted(tmp_path) -> None:
    regular = tmp_path / "data.tsv"
    regular.write_bytes(b"x\t1\n")
    assert restore_state._file_fingerprint(regular) == {
        "sizeBytes": 4, "sha256": hashlib.sha256(b"x\t1\n").hexdigest(),
    }
    assert restore_state._file_fingerprint(tmp_path) is None
    assert restore_state._file_fingerprint(tmp_path / "missing.tsv") is None
    if hasattr(os, "mkfifo"):
        fifo = tmp_path / "pipe"
        os.mkfifo(fifo)
        # Opening a FIFO with no writer blocks; reaching the assert is the test.
        assert restore_state._file_fingerprint(fifo) is None
    if Path("/dev/zero").exists():
        assert restore_state._file_fingerprint(Path("/dev/zero")) is None
