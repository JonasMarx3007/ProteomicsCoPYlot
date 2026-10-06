import gzip
import io
import json
from pathlib import Path

import pytest
from fastapi import UploadFile
from fastapi.testclient import TestClient

from app.main import app
from app.services import restore_state
from app.services.password_hashing import hash_password


@pytest.fixture
def client(monkeypatch, tmp_path):
    access = tmp_path / "access.json"
    access.write_text(json.dumps({"password_pbkdf2_sha256": hash_password("restore-test-only")}))
    monkeypatch.setenv("COPYLOT_TOOL_ACCESS_ENABLED", "1")
    monkeypatch.setenv("COPYLOT_TOOL_ACCESS_FILE", str(access))
    monkeypatch.setenv("COPYLOT_SESSION_ISOLATION", "1")
    monkeypatch.setenv("COPYLOT_ALLOW_LOCAL_PATH_APIS", "1")
    with TestClient(app, client=("198.51.100.10", 50000)) as client:
        assert client.post("/api/tool/auth/login", json={"password": "restore-test-only"}).status_code == 200
        yield client


def test_remote_restore_requires_uploads_and_preserves_state_until_complete(client, tmp_path, monkeypatch):
    original = b"ProteinNames,A1,A2,B1,B2\nSAFE,1,2,3,4\n"
    assert client.post("/api/datasets/upload", data={"kind": "protein"},
                       files={"file": ("original.csv", original)}).status_code == 200
    exported = client.post("/api/restore/export", json={"portable": True, "uiState": {"test": True}})
    assert exported.status_code == 200
    state = json.loads(gzip.decompress(exported.content))
    package = next(p for p in state["backend"]["packages"] if p["datasets"]["protein"])
    forbidden = tmp_path / "server-secret.csv"
    forbidden.write_text("ProteinNames,A1\nSECRET,999\n")
    package["datasets"]["protein"]["path"] = str(forbidden)
    exists = Path.exists

    def guarded_exists(path):
        assert path != forbidden, "Remote restore probed a client-supplied server path"
        return exists(path)

    monkeypatch.setattr(Path, "exists", guarded_exists)
    blob = gzip.compress(json.dumps(state).encode())
    response = client.post("/api/restore/import", files={"stateFile": ("state.copylotstate", blob)})
    assert response.status_code == 409
    assert response.json()["missingFiles"][0]["expectedPath"] is None
    assert client.get("/api/datasets/current").json()["protein"]["filename"] == "original.csv"
    manifest = [{"packageName": package["name"], "kind": "protein", "sourcePath": str(forbidden)}]
    restored = client.post("/api/restore/import", data={"replacementsManifest": json.dumps(manifest)},
                           files=[("stateFile", ("state.copylotstate", blob)),
                                  ("replacements", ("replacement.csv", original))])
    assert restored.status_code == 200, restored.text
    assert restored.json()["ok"] and restored.json()["uiState"]["test"]
    dataset = client.get("/api/datasets/current").json()["protein"]
    assert dataset["filename"] == "replacement.csv"
    assert dataset.get("sourcePath") is None


@pytest.mark.parametrize("path", ["/etc/passwd", "../../secret.tsv", "C:/secret.tsv", "//server/share/secret.tsv"])
def test_remote_peptide_replacements_never_retain_supplied_paths(path, tmp_path, monkeypatch):
    monkeypatch.setattr(restore_state, "_restore_upload_dir", lambda: tmp_path)
    state = {"backend": {"packages": [{"name": "Data", "datasets": {
        "peptide": {"filename": "peptide.tsv", "path": path}}}]}}
    replacement = restore_state.ReplacementInput(
        file=UploadFile(filename="peptide.tsv", file=io.BytesIO(b"uploaded content")),
        source_path=path, size_bytes=16,
    )
    mapped = {("Data", "peptide"): replacement}
    assert restore_state.inspect_missing_files(state, mapped, allow_local_paths=False) == []
    prepared = restore_state._prepare_restore_inputs(state, mapped, allow_local_paths=False)
    saved, provenance = prepared.peptide_path_by_package["Data"]
    assert Path(saved).parent == tmp_path and provenance is None
    assert Path(saved).read_bytes() == b"uploaded content"


def test_restore_auth_and_viewer_gates_still_apply(client, monkeypatch):
    client.post("/api/tool/auth/logout")
    assert client.post("/api/restore/import").status_code == 401
    assert client.post("/api/tool/auth/login", json={"password": "restore-test-only"}).status_code == 200
    monkeypatch.setenv("COPYLOT_VIEWER_MODE", "1")
    assert client.post("/api/restore/import").status_code == 403
