from __future__ import annotations

import io
import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.viewer_portal import (
    ViewerAccessEntry,
    _password_matches,
    _warn_about_legacy_credential,
)
from app.services.password_hashing import hash_password

SECRET = "correct horse battery staple"


def _entry(**overrides) -> ViewerAccessEntry:
    values = {
        "project": "GRK_project",
        "project_label": "GRK",
        "password": "",
        "password_sha256": "",
        "password_pbkdf2_sha256": "",
    }
    values.update(overrides)
    return ViewerAccessEntry(**values)


def _captured_warning(entry: ViewerAccessEntry) -> str:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("app.services.viewer_portal")
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    try:
        _warn_about_legacy_credential(entry)
    finally:
        logger.removeHandler(handler)
    return stream.getvalue()


def test_recommended_form_warns_about_nothing() -> None:
    assert _captured_warning(_entry(password_pbkdf2_sha256=hash_password(SECRET))) == ""


def test_plaintext_password_is_reported() -> None:
    warning = _captured_warning(_entry(password=SECRET))
    assert "plaintext" in warning
    assert "GRK_project" in warning
    assert "password_pbkdf2_sha256" in warning, "the warning should say what to use instead"


def test_unsalted_hash_is_reported() -> None:
    warning = _captured_warning(_entry(password_sha256="9f86d081884c7d65" * 4))
    assert "unsalted" in warning
    assert "GRK_project" in warning


@pytest.mark.parametrize(
    "entry",
    [
        _entry(password=SECRET),
        _entry(password_sha256="9f86d081884c7d65" * 4),
        _entry(password=SECRET, password_sha256="9f86d081884c7d65" * 4),
    ],
)
def test_the_credential_itself_is_never_logged(entry: ViewerAccessEntry) -> None:
    warning = _captured_warning(entry)
    assert SECRET not in warning
    assert entry.password_sha256 not in warning or not entry.password_sha256


def test_a_stronger_form_present_suppresses_the_warning() -> None:
    entry = _entry(password=SECRET, password_pbkdf2_sha256=hash_password(SECRET))
    assert _captured_warning(entry) == ""


def test_warning_does_not_change_authentication() -> None:
    for entry in (
        _entry(password_pbkdf2_sha256=hash_password(SECRET)),
        _entry(password=SECRET),
    ):
        assert _password_matches(SECRET, entry) is True
        assert _password_matches("wrong", entry) is False


def _tool_warning(data: dict) -> str:
    import logging

    from app.services import tool_access

    records: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage() % record.args if record.args else record.getMessage())

    handler = _Capture()
    tool_access.LOGGER.addHandler(handler)
    try:
        tool_access._warn_about_legacy_credential(data)
    finally:
        tool_access.LOGGER.removeHandler(handler)
    return " ".join(records)


def test_tool_access_pbkdf2_warns_about_nothing() -> None:
    from app.services.password_hashing import hash_password

    assert _tool_warning({"password_pbkdf2_sha256": hash_password(SECRET)}) == ""


def test_tool_access_unsalted_hash_is_reported() -> None:
    import hashlib

    digest = hashlib.sha256(SECRET.encode("utf-8")).hexdigest()
    warning = _tool_warning({"password_sha256": digest})
    assert "unsalted SHA-256" in warning
    assert "password_pbkdf2_sha256" in warning, "the warning must name the better option"


def test_tool_access_never_logs_the_credential() -> None:
    import hashlib

    digest = hashlib.sha256(SECRET.encode("utf-8")).hexdigest()
    warning = _tool_warning({"password_sha256": digest})
    assert SECRET not in warning
    assert digest not in warning, "the hash itself must not be logged either"


def test_a_stronger_tool_credential_suppresses_the_warning() -> None:
    import hashlib

    from app.services.password_hashing import hash_password

    warning = _tool_warning(
        {
            "password_sha256": hashlib.sha256(SECRET.encode("utf-8")).hexdigest(),
            "password_pbkdf2_sha256": hash_password(SECRET),
        }
    )
    assert warning == ""


def test_the_tool_warning_does_not_change_authentication() -> None:
    import hashlib
    import json
    import tempfile
    from pathlib import Path

    from app.services import tool_access

    digest = hashlib.sha256(SECRET.encode("utf-8")).hexdigest()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "local").mkdir()
        (root / "local" / "tool_access.local.json").write_text(
            json.dumps({"password_sha256": digest, "tokens": []}), encoding="utf-8"
        )
        tool_access.authenticate_tool_password(SECRET, project_root=root)
        with pytest.raises(ValueError, match="Invalid tool password"):
            tool_access.authenticate_tool_password("wrong", project_root=root)


def test_validating_the_config_actually_emits_the_warning(monkeypatch) -> None:
    import hashlib
    import json
    import logging
    import tempfile
    from pathlib import Path

    from app.services import tool_access

    digest = hashlib.sha256(SECRET.encode("utf-8")).hexdigest()
    records: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage() % record.args if record.args else record.getMessage())

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "local").mkdir()
        (root / "local" / "tool_access.local.json").write_text(
            json.dumps({"password_sha256": digest, "tokens": []}), encoding="utf-8"
        )
        monkeypatch.setattr(tool_access, "_load_access", lambda *a, **k: {
            "password_sha256": digest, "tokens": []
        })
        handler = _Capture()
        tool_access.LOGGER.addHandler(handler)
        try:
            tool_access.validate_tool_access_configuration()
        finally:
            tool_access.LOGGER.removeHandler(handler)

    assert any("unsalted SHA-256" in message for message in records), (
        "validate_tool_access_configuration accepted a legacy hash without reporting it"
    )
