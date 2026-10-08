from __future__ import annotations

import logging

import json
import os
import secrets
from pathlib import Path
from threading import RLock

from app.services.password_hashing import normalize_sha256, sha256_hex, validate_password_hash, verify_password
from app.services.session_context import get_session_id
from app.services.env_settings import env_flag

LOGGER = logging.getLogger(__name__)


PROJECT_ROOT = Path(__file__).resolve().parents[3]

_SESSION_AUTH: set[str] = set()
_SESSION_LOCK = RLock()


def tool_access_enabled() -> bool:
    return env_flag("COPYLOT_TOOL_ACCESS_ENABLED")


def _access_file_candidates(project_root: Path | None = None) -> list[Path]:
    root = project_root or PROJECT_ROOT
    env_path = str(os.getenv("COPYLOT_TOOL_ACCESS_FILE", "")).strip()
    candidates: list[Path] = []
    if env_path:
        candidates.append(Path(env_path))
    candidates.extend(
        [
            root / "local" / "tool_access.local.json",
            root / "tool_access.local.json",
            root / "tool_access.json",
        ]
    )
    return candidates


def _access_file_path(project_root: Path | None = None) -> Path | None:
    for candidate in _access_file_candidates(project_root):
        if candidate.is_file():
            return candidate
    return None


def _load_access(project_root: Path | None = None) -> dict[str, object]:
    path = _access_file_path(project_root)
    if path is None:
        raise FileNotFoundError("Tool access is enabled but no local/tool_access.local.json file was found.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        LOGGER.error("Invalid JSON in tool access file %s: %s", path, exc)
        raise ValueError(
            f"The tool access file '{path.name}' does not contain valid JSON."
        ) from exc
    if not isinstance(data, dict):
        raise ValueError("Tool access file must contain a JSON object.")
    return data


def _password_pbkdf2_hash(data: dict[str, object]) -> str:
    """The PBKDF2 hash the tool password is checked against; the only form accepted.

    An unsalted `password_sha256` was accepted with a warning until 2026-09. A
    digest of a human-chosen password without salt or stretching falls to a
    precomputed table if the file is ever read, so a file that still carries
    one now fails validation and is told what to store instead.
    """
    if str(data.get("password_sha256", "")).strip() and not str(data.get("password_pbkdf2_sha256", "")).strip():
        raise ValueError(
            "Tool access file uses an unsalted password_sha256 hash, which is no longer accepted. "
            "Store a PBKDF2 hash as password_pbkdf2_sha256 instead (see docs/INSTALLATION.md)."
        )
    raw = str(data.get("password_pbkdf2_sha256", "")).strip()
    if not raw:
        raise ValueError("Tool access file must define password_pbkdf2_sha256.")
    validate_password_hash(raw)
    return raw


def _token_hashes(data: dict[str, object]) -> list[str]:
    values = data.get("tokens", [])
    if not isinstance(values, list):
        raise ValueError("Tool access tokens must be a list.")
    hashes: list[str] = []
    for item in values:
        if isinstance(item, str):
            hashes.append(normalize_sha256(item))
        elif isinstance(item, dict):
            hashes.append(normalize_sha256(str(item.get("token_sha256", ""))))
        else:
            raise ValueError("Tool access token entries must be strings or objects.")
    return hashes


def tool_session_authenticated() -> bool:
    if not tool_access_enabled():
        return True
    with _SESSION_LOCK:
        return get_session_id() in _SESSION_AUTH


def validate_tool_access_configuration() -> None:
    data = _load_access()
    _password_pbkdf2_hash(data)
    for token_hash in _token_hashes(data):
        if not any(character != "0" for character in token_hash):
            raise ValueError("Tool access token still contains the example placeholder.")


def _grant_authenticated_session() -> str:
    """Bind authentication to a fresh session id, discarding the one the client sent.

    Rotating here is what stops session fixation: the pre-login id never becomes
    an authenticated one, so planting it achieves nothing.
    """
    from app.services.session_cleanup import authenticated_session_rotation

    with authenticated_session_rotation() as replacement:
        with _SESSION_LOCK:
            _SESSION_AUTH.add(replacement)
    return replacement


def authenticate_tool_password(password: str, *, project_root: Path | None = None) -> str:
    data = _load_access(project_root)
    candidate = str(password or "")
    if not verify_password(candidate, _password_pbkdf2_hash(data)):
        raise ValueError("Invalid tool password.")
    return _grant_authenticated_session()


def authenticate_tool_token(token: str, *, project_root: Path | None = None) -> str:
    data = _load_access(project_root)
    digest = sha256_hex(str(token or ""))
    if not any(secrets.compare_digest(digest, expected) for expected in _token_hashes(data)):
        raise ValueError("Invalid tool access token.")
    return _grant_authenticated_session()


def clear_tool_session_auth() -> None:
    from app.services.notebook_snapshots import forget_session
    with _SESSION_LOCK:
        _SESSION_AUTH.discard(get_session_id())
    forget_session(get_session_id())
