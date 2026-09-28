from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

from app.services.annotation_store import reset_all_annotations
from app.services.condition_palette_store import reset_condition_palettes
from app.services.dataset_store import reset_all_datasets
from app.services.metadata_upload_store import reset_all_uploaded_metadata
from app.services.password_hashing import validate_password_hash, verify_password
from app.services.peptide_metadata_store import clear_peptide_metadata
from app.services.session_context import get_session_id, session_isolation_enabled
from app.services.viewer_bootstrap import (
    load_viewer_state,
    resolve_viewer_project_config,
    viewer_mode_enabled,
)

LOGGER = logging.getLogger(__name__)
TRUTHY_VALUES = {"1", "true", "yes", "on"}
# Must contain at least one character that is not a dot: the name is used as a
# single path segment, so a name of "." or ".." would resolve outside its own
# project directory. Names come from admin-controlled config today, but the
# containment should not depend on that staying true.
_PROJECT_NAME_RE = re.compile(r"^(?=.*[^.])[A-Za-z0-9_.-]{1,128}$")


@dataclass(frozen=True)
class ViewerAccessEntry:
    project: str
    project_label: str
    password_pbkdf2_sha256: str


@dataclass(frozen=True)
class ViewerQrAccessEntry:
    project: str
    project_label: str
    token_sha256: str


@dataclass(frozen=True)
class ViewerSessionAuth:
    project: str
    project_label: str


_LOCK = RLock()
_SESSION_AUTH: dict[str, ViewerSessionAuth] = {}
_BOOTSTRAPPED_SESSION_PROJECT: dict[str, str] = {}
_ACCESS_FILE_CACHE_KEY: tuple[str, float, int] | None = None
_ACCESS_FILE_CACHE: list[ViewerAccessEntry] = []
_QR_ACCESS_FILE_CACHE_KEY: tuple[str, float, int] | None = None
_QR_ACCESS_FILE_CACHE: list[ViewerQrAccessEntry] = []


def _truthy_env(name: str, default: str = "0") -> bool:
    return str(os.getenv(name, default)).strip().lower() in TRUTHY_VALUES


def viewer_portal_enabled() -> bool:
    if not viewer_mode_enabled():
        return False
    if not session_isolation_enabled():
        return False
    return _truthy_env("COPYLOT_VIEWER_PORTAL_ENABLED", "0")


def _default_access_file_candidates(project_root: Path) -> list[Path]:
    return [
        project_root / "local" / "viewer_access.local.json",
        project_root / "viewer_access.local.json",
        project_root / "viewer_access.json",
    ]


def _resolve_access_file(project_root: Path) -> Path | None:
    raw = str(os.getenv("COPYLOT_VIEWER_ACCESS_FILE", "")).strip()
    if raw:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = project_root / candidate
        return candidate.resolve()

    for candidate in _default_access_file_candidates(project_root):
        if candidate.is_file():
            return candidate.resolve()
    return None


def _default_qr_access_file_candidates(project_root: Path) -> list[Path]:
    return [
        project_root / "local" / "viewer_qr_access.local.json",
        project_root / "viewer_qr_access.local.json",
        project_root / "viewer_qr_access.json",
    ]


def _resolve_qr_access_file(project_root: Path) -> Path | None:
    raw = str(os.getenv("COPYLOT_VIEWER_QR_ACCESS_FILE", "")).strip()
    if raw:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = project_root / candidate
        return candidate.resolve()

    for candidate in _default_qr_access_file_candidates(project_root):
        if candidate.is_file():
            return candidate.resolve()
    return None


def _normalize_project_name(value: str) -> str:
    project = str(value or "").strip()
    if not _PROJECT_NAME_RE.fullmatch(project):
        raise ValueError(
            "Viewer access entry project name is invalid. Allowed characters: "
            "letters, numbers, dot, underscore, hyphen."
        )
    return project


def _refuse_legacy_credential(raw: dict[str, Any], *, index: int, project: str) -> None:
    """Plaintext and unsalted SHA-256 passwords are refused, not merely warned about.

    Plaintext is readable by anyone who can open the file; an unsalted digest
    of a human-chosen password falls to a precomputed table. Both were
    accepted with a log warning until 2026-09; a deployment that still carries
    one now fails to start and is told what to store instead.
    """
    if str(raw.get("password", "")):
        form = "a plaintext 'password'"
    elif str(raw.get("password_sha256", "")).strip():
        form = "an unsalted 'password_sha256' hash"
    else:
        return
    raise ValueError(
        f"Viewer access entry #{index} ({project or 'no project'}) uses {form}, which is no "
        "longer accepted. Store a PBKDF2 hash as password_pbkdf2_sha256 instead "
        "(see docs/INSTALLATION.md for the one-line command that generates it)."
    )


def _normalize_sha256(value: str) -> str:
    """A 64-hex SHA-256 digest as stored for QR tokens (random secrets, so a
    plain digest is adequate there; passwords are PBKDF2 only)."""
    digest = str(value or "").strip().lower()
    if not digest:
        return ""
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError("token_sha256 must be a 64-character lowercase hex digest.")
    return digest


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _entry_from_object(raw: dict[str, Any], *, index: int) -> ViewerAccessEntry:
    project = _normalize_project_name(str(raw.get("project", "")))
    project_label = str(raw.get("label", project)).strip() or project
    _refuse_legacy_credential(raw, index=index, project=project)
    password_pbkdf2_sha256 = str(raw.get("password_pbkdf2_sha256", "")).strip()
    if not password_pbkdf2_sha256:
        raise ValueError(
            f"Viewer access entry #{index} ({project}) must define password_pbkdf2_sha256."
        )
    validate_password_hash(password_pbkdf2_sha256)
    return ViewerAccessEntry(
        project=project,
        project_label=project_label,
        password_pbkdf2_sha256=password_pbkdf2_sha256,
    )


def _qr_entry_from_object(raw: dict[str, Any], *, index: int) -> ViewerQrAccessEntry:
    project = _normalize_project_name(str(raw.get("project", "")))
    project_label = str(raw.get("label", project)).strip() or project
    token_sha256 = _normalize_sha256(str(raw.get("token_sha256", "")))
    token = str(raw.get("token", ""))
    if not token_sha256 and token:
        token_sha256 = _hash_token(token)
    if not token_sha256:
        raise ValueError(
            f"Viewer QR access token #{index} must define token_sha256."
        )
    return ViewerQrAccessEntry(
        project=project,
        project_label=project_label,
        token_sha256=token_sha256,
    )


def _parse_access_entries(raw: Any) -> list[ViewerAccessEntry]:
    entries: list[ViewerAccessEntry] = []
    if isinstance(raw, dict):
        if isinstance(raw.get("credentials"), list):
            for idx, item in enumerate(raw["credentials"], start=1):
                if not isinstance(item, dict):
                    raise ValueError("viewer access credentials items must be objects.")
                entries.append(_entry_from_object(item, index=idx))
            return entries

        if isinstance(raw.get("passwords"), dict):
            # The pre-2026 layout keyed projects by their plaintext password.
            raise ValueError(
                "viewer access file uses the 'passwords' object, which stores plaintext "
                "passwords and is no longer accepted. Use a 'credentials' list with "
                "password_pbkdf2_sha256 entries (see docs/INSTALLATION.md)."
            )

    raise ValueError("viewer access file must contain a 'credentials' list.")


def _parse_qr_access_entries(raw: Any) -> list[ViewerQrAccessEntry]:
    entries: list[ViewerQrAccessEntry] = []
    if isinstance(raw, dict) and isinstance(raw.get("tokens"), list):
        for idx, item in enumerate(raw["tokens"], start=1):
            if not isinstance(item, dict):
                raise ValueError("viewer QR access token items must be objects.")
            entries.append(_qr_entry_from_object(item, index=idx))
        return entries
    raise ValueError("viewer QR access file must contain a 'tokens' list.")


def _load_access_entries(project_root: Path) -> list[ViewerAccessEntry]:
    global _ACCESS_FILE_CACHE_KEY
    global _ACCESS_FILE_CACHE

    path = _resolve_access_file(project_root)
    if path is None:
        return []

    stat = path.stat()
    cache_key = (str(path), stat.st_mtime, stat.st_size)

    with _LOCK:
        if _ACCESS_FILE_CACHE_KEY == cache_key:
            return list(_ACCESS_FILE_CACHE)

    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    parsed = _parse_access_entries(raw)

    with _LOCK:
        _ACCESS_FILE_CACHE_KEY = cache_key
        _ACCESS_FILE_CACHE = list(parsed)
    return parsed


def _load_qr_access_entries(project_root: Path) -> list[ViewerQrAccessEntry]:
    global _QR_ACCESS_FILE_CACHE_KEY
    global _QR_ACCESS_FILE_CACHE

    path = _resolve_qr_access_file(project_root)
    if path is None:
        return []

    stat = path.stat()
    cache_key = (str(path), stat.st_mtime, stat.st_size)

    with _LOCK:
        if _QR_ACCESS_FILE_CACHE_KEY == cache_key:
            return list(_QR_ACCESS_FILE_CACHE)

    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    parsed = _parse_qr_access_entries(raw)

    with _LOCK:
        _QR_ACCESS_FILE_CACHE_KEY = cache_key
        _QR_ACCESS_FILE_CACHE = list(parsed)
    return parsed


def _password_matches(raw_password: str, entry: ViewerAccessEntry) -> bool:
    return verify_password(raw_password, entry.password_pbkdf2_sha256)


def validate_viewer_portal_configuration() -> None:
    root = Path(__file__).resolve().parents[3]
    entries = _load_access_entries(root)
    if not entries:
        raise ValueError("Viewer portal has no configured password credentials.")
    for entry in entries:
        if resolve_viewer_project_config(entry.project) is None:
            raise ValueError(f"Viewer project '{entry.project}' has no viewer_config.json.")

    qr_entries = _load_qr_access_entries(root)
    for entry in qr_entries:
        if not any(character != "0" for character in entry.token_sha256):
            raise ValueError("Viewer QR token still contains the example placeholder.")
        if resolve_viewer_project_config(entry.project) is None:
            raise ValueError(f"Viewer project '{entry.project}' has no viewer_config.json.")


def _reset_current_session_data() -> None:
    reset_all_annotations()
    reset_all_uploaded_metadata()
    reset_all_datasets()
    reset_condition_palettes()
    clear_peptide_metadata()


def _load_project_into_current_session(project_name: str, *, force_reload: bool) -> None:
    session_id = get_session_id()
    project = _normalize_project_name(project_name)
    if not force_reload:
        with _LOCK:
            if _BOOTSTRAPPED_SESSION_PROJECT.get(session_id) == project:
                return

    config_path = resolve_viewer_project_config(project)
    if config_path is None:
        raise FileNotFoundError(
            f"Viewer project '{project}' has no viewer_config.json in "
            "viewer_data/local/<project>/, viewer_data/<project>/, or viewer_data/projects/<project>/."
        )

    _reset_current_session_data()
    result = load_viewer_state(config_path)
    LOGGER.info(
        "Viewer portal loaded project '%s' from %s (datasets=%d, annotations=%d).",
        project,
        config_path,
        len(result.loaded_datasets),
        len(result.loaded_annotations),
    )
    for warning in result.warnings:
        LOGGER.warning("Viewer portal bootstrap warning (%s): %s", project, warning)

    with _LOCK:
        _BOOTSTRAPPED_SESSION_PROJECT[session_id] = project


def viewer_session_authenticated() -> bool:
    with _LOCK:
        return get_session_id() in _SESSION_AUTH


def viewer_session_auth() -> ViewerSessionAuth | None:
    with _LOCK:
        return _SESSION_AUTH.get(get_session_id())


def _initialize_authenticated_viewer(project: str, project_label: str) -> ViewerSessionAuth:
    from app.services.session_cleanup import authenticated_session_rotation

    auth = ViewerSessionAuth(project=project, project_label=project_label)
    with authenticated_session_rotation() as session_id:
        _load_project_into_current_session(project, force_reload=True)
        with _LOCK:
            _SESSION_AUTH[session_id] = auth
    return auth


def authenticate_viewer_session(password: str, *, project_root: Path | None = None) -> ViewerSessionAuth:
    if not viewer_portal_enabled():
        raise RuntimeError("Viewer portal auth is not enabled.")

    candidate_password = str(password or "")
    if not candidate_password:
        raise ValueError("Password must not be empty.")

    root = project_root or Path(__file__).resolve().parents[3]
    entries = _load_access_entries(root)
    if not entries:
        raise RuntimeError(
            "Viewer portal is enabled but no credentials are configured. "
            "Create local/viewer_access.local.json."
        )

    selected: ViewerAccessEntry | None = None
    for entry in entries:
        if _password_matches(candidate_password, entry):
            selected = entry
            break

    if selected is None:
        raise ValueError("Invalid viewer password.")

    return _initialize_authenticated_viewer(selected.project, selected.project_label)


def authenticate_viewer_qr_session(token: str, *, project_root: Path | None = None) -> ViewerSessionAuth:
    if not viewer_portal_enabled():
        raise RuntimeError("Viewer portal auth is not enabled.")

    candidate_token = str(token or "").strip()
    if not candidate_token:
        raise ValueError("QR token must not be empty.")

    root = project_root or Path(__file__).resolve().parents[3]
    entries = _load_qr_access_entries(root)
    if not entries:
        raise RuntimeError(
            "Viewer QR access is not configured. Create local/viewer_qr_access.local.json."
        )

    digest = _hash_token(candidate_token)
    selected: ViewerQrAccessEntry | None = None
    for entry in entries:
        if secrets.compare_digest(digest, entry.token_sha256):
            selected = entry
            break

    if selected is None:
        raise ValueError("Invalid viewer QR token.")

    return _initialize_authenticated_viewer(selected.project, selected.project_label)


def clear_viewer_session_auth(*, reset_data: bool = False) -> None:
    session_id = get_session_id()
    with _LOCK:
        _SESSION_AUTH.pop(session_id, None)
        _BOOTSTRAPPED_SESSION_PROJECT.pop(session_id, None)
    if reset_data:
        _reset_current_session_data()


def ensure_viewer_session_bootstrapped(*, force_reload: bool = False) -> ViewerSessionAuth:
    auth = viewer_session_auth()
    if auth is None:
        raise PermissionError("Viewer authentication is required.")
    _load_project_into_current_session(auth.project, force_reload=force_reload)
    return auth
