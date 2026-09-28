"""Plaintext and unsalted-SHA-256 credentials are refused, not warned about.

Until 2026-09 both the viewer access file and the tool access file accepted
`password` / `password_sha256` next to PBKDF2 hashes and only logged a
warning. Plaintext is readable by anyone who can open the file; an unsalted
digest of a human-chosen password falls to a precomputed table. A file that
still carries one now fails validation with a message naming the entry and
what to store instead, and nothing weaker than PBKDF2 is ever compared.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services import tool_access, viewer_portal
from app.services.password_hashing import hash_password
from app.services.viewer_portal import ViewerAccessEntry, _entry_from_object, _password_matches

SECRET = "correct horse battery staple"


def test_a_pbkdf2_entry_is_accepted_and_authenticates():
    entry = _entry_from_object({"project": "example_project", "password_pbkdf2_sha256": hash_password(SECRET)}, index=1)
    assert entry.project == "example_project"
    assert _password_matches(SECRET, entry) is True
    assert _password_matches("wrong", entry) is False


def test_a_plaintext_viewer_password_is_refused():
    with pytest.raises(ValueError) as excinfo:
        _entry_from_object({"project": "example_project", "password": SECRET}, index=2)
    message = str(excinfo.value)
    assert "entry #2 (example_project) uses a plaintext 'password'" in message
    assert "password_pbkdf2_sha256" in message
    assert SECRET not in message


def test_an_unsalted_viewer_hash_is_refused_even_next_to_a_pbkdf2_hash():
    digest = hashlib.sha256(SECRET.encode()).hexdigest()
    with pytest.raises(ValueError, match="unsalted 'password_sha256'"):
        _entry_from_object({"project": "example_project", "password_sha256": digest}, index=1)
    with pytest.raises(ValueError, match="unsalted 'password_sha256'"):
        _entry_from_object(
            {"project": "example_project", "password_sha256": digest, "password_pbkdf2_sha256": hash_password(SECRET)},
            index=1,
        )


def test_an_entry_without_any_credential_is_refused():
    with pytest.raises(ValueError, match="must define password_pbkdf2_sha256"):
        _entry_from_object({"project": "example_project"}, index=3)


def test_the_old_passwords_object_layout_is_refused(tmp_path, monkeypatch):
    access = tmp_path / "viewer_access.json"
    access.write_text(json.dumps({"passwords": {SECRET: "example_project"}}), encoding="utf-8")
    monkeypatch.setenv("COPYLOT_VIEWER_ACCESS_FILE", str(access))
    with pytest.raises(ValueError, match="'passwords' object, which stores plaintext"):
        viewer_portal._load_access_entries(ROOT)


def test_the_entry_type_has_no_room_for_weaker_forms():
    assert set(ViewerAccessEntry.__dataclass_fields__) == {"project", "project_label", "password_pbkdf2_sha256"}


def test_tool_access_pbkdf2_is_the_only_accepted_form():
    assert tool_access._password_pbkdf2_hash({"password_pbkdf2_sha256": hash_password(SECRET)})
    with pytest.raises(ValueError, match="unsalted password_sha256"):
        tool_access._password_pbkdf2_hash({"password_sha256": hashlib.sha256(SECRET.encode()).hexdigest()})
    with pytest.raises(ValueError, match="must define password_pbkdf2_sha256"):
        tool_access._password_pbkdf2_hash({"tokens": []})


def test_tool_login_uses_only_the_pbkdf2_hash(tmp_path, monkeypatch):
    access = tmp_path / "tool_access.json"
    access.write_text(json.dumps({"password_pbkdf2_sha256": hash_password(SECRET), "tokens": []}), encoding="utf-8")
    monkeypatch.setenv("COPYLOT_TOOL_ACCESS_FILE", str(access))
    monkeypatch.setattr(tool_access, "_grant_authenticated_session", lambda: "session")
    assert tool_access.authenticate_tool_password(SECRET) == "session"
    with pytest.raises(ValueError, match="Invalid tool password"):
        tool_access.authenticate_tool_password("wrong")


def test_viewer_portal_startup_validation_runs_with_pbkdf2_and_qr_entries(tmp_path, monkeypatch):
    """The whole startup path, not just the parsers: a QR token file is parsed too."""
    access = tmp_path / "viewer_access.json"
    access.write_text(
        json.dumps({"credentials": [{"project": "HEK293", "password_pbkdf2_sha256": hash_password(SECRET)}]}),
        encoding="utf-8",
    )
    qr = tmp_path / "viewer_qr_access.json"
    qr.write_text(
        json.dumps({"tokens": [{"project": "HEK293", "token_sha256": hashlib.sha256(b"qr-secret").hexdigest()}]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("COPYLOT_VIEWER_ACCESS_FILE", str(access))
    monkeypatch.setenv("COPYLOT_VIEWER_QR_ACCESS_FILE", str(qr))
    viewer_portal.validate_viewer_portal_configuration()
