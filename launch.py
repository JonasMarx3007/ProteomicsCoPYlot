from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import sys
import threading
import webbrowser
from pathlib import Path

_PROJECT_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_TRUTHY_VALUES = {"1", "true", "yes", "on"}


def _truthy_env(name: str, default: str = "") -> bool:
    return str(os.getenv(name, default)).strip().lower() in _TRUTHY_VALUES


def _host_is_loopback(host: str) -> bool:
    """Return whether a bind host is unambiguously local to this machine."""
    value = str(host or "").strip().lower().rstrip(".")
    if value == "localhost":
        return True
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        # Hostnames other than localhost may resolve to a network interface and
        # are therefore treated as non-loopback unless the operator opts in.
        return False
    if address.version == 6 and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return bool(address.is_loopback)


def _validate_network_binding(host: str, *, allow_unsafe_public: bool) -> None:
    """Fail closed before exposing the application on a network interface."""
    if _host_is_loopback(host):
        return

    authentication_enabled = _truthy_env("COPYLOT_TOOL_ACCESS_ENABLED") or _truthy_env(
        "COPYLOT_VIEWER_PORTAL_ENABLED"
    )
    # Must match app.services.session_context.session_isolation_enabled, which
    # defaults this on. Reading it as off here refused a non-loopback bind to an
    # operator who was relying on the safe default.
    session_isolation = _truthy_env("COPYLOT_SESSION_ISOLATION", "1")
    if authentication_enabled and session_isolation:
        return
    if allow_unsafe_public:
        print(
            "WARNING: starting Proteomics CoPYlot on a non-loopback interface without "
            "authenticated session isolation. Server-local path APIs remain blocked for "
            "remote clients, but the remaining API is publicly reachable.",
            file=sys.stderr,
        )
        return
    raise ValueError(
        f"Refusing to bind Proteomics CoPYlot to non-loopback host '{host}' without "
        "authentication and session isolation. Enable COPYLOT_TOOL_ACCESS_ENABLED=1 "
        "or COPYLOT_VIEWER_PORTAL_ENABLED=1 together with COPYLOT_SESSION_ISOLATION=1, "
        "or pass --allow-unsafe-public to acknowledge the risk explicitly."
    )


def _project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _bundle_root() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return _project_root()


def _ensure_backend_on_path(project_root: Path, bundle_root: Path) -> None:
    candidates = [
        project_root / "backend",
        bundle_root / "backend",
    ]
    for candidate in candidates:
        if candidate.exists():
            sys.path.insert(0, str(candidate))
            return


def _set_frontend_dist_env(project_root: Path, bundle_root: Path) -> None:
    if os.getenv("COPYLOT_FRONTEND_DIST", "").strip():
        return

    candidates = [
        project_root / "frontend_dist",
        bundle_root / "frontend_dist",
        project_root / "frontend" / "dist",
    ]
    for candidate in candidates:
        if (candidate / "index.html").is_file():
            os.environ["COPYLOT_FRONTEND_DIST"] = str(candidate)
            return


def frontend_bundle_mode(dist: Path) -> str | None:
    """Which mode the bundle in `dist` was built for, or None if it cannot say.

    Vite writes `build-mode.json` from VITE_APP_MODE. A bundle built before that
    existed has no marker, which is not the same as being built for analysis.
    """
    marker = dist / "build-mode.json"
    if not marker.is_file():
        return None
    try:
        mode = json.loads(marker.read_text(encoding="utf-8")).get("appMode")
    except (OSError, ValueError):
        return None
    return mode if mode in {"analysis", "viewer"} else None


def viewer_mode_requested(viewer_flag: bool) -> bool:
    """Whether this process will serve the viewer.

    `--viewer` is one way in; `COPYLOT_VIEWER_MODE=1` is the other, and it is the
    one the backend itself reads. The Docker images start `launch.py` without
    flags and select viewer mode through the environment, so the bundle check
    has to honour both or every viewer container refuses its own viewer bundle.
    """
    return bool(viewer_flag) or _truthy_env("COPYLOT_VIEWER_MODE")


def check_frontend_bundle_mode(viewer: bool) -> str | None:
    """Refuse to serve a bundle built for the other mode. Returns a warning.

    The two bundles are byte-different builds of the same source and the mode is
    invisible once built, so a viewer backend serving the analysis bundle shows
    every data-processing module -- Upload, Imputation, Restore, peptide
    collapse, simulation -- over read-only data, with nothing on screen to say
    the gating is not running. That is silent, and it is the failure this
    catches. Raises ValueError on a definite mismatch; returns a message when
    the bundle predates the marker and cannot be checked.
    """
    configured = os.getenv("COPYLOT_FRONTEND_DIST", "").strip()
    if not configured:
        return None
    dist = Path(configured)
    wanted = "viewer" if viewer else "analysis"
    found = frontend_bundle_mode(dist)
    if found is None:
        return (
            f"Cannot tell which mode the frontend bundle in {dist} was built for "
            "(no build-mode.json). Rebuild it to be sure: in frontend/, "
            f'cmd /c "set VITE_APP_MODE={wanted}&& npm run build".'
        )
    if found != wanted:
        raise ValueError(
            f"The frontend bundle in {dist} was built for {found} mode, but this "
            f"is the {wanted} launcher. Serving it would show the {found} UI: in "
            "viewer mode that means every data-processing module on screen over "
            "read-only data, with no gating. Rebuild in frontend/ with "
            f'cmd /c "set VITE_APP_MODE={wanted}&& npm run build", or point '
            "COPYLOT_FRONTEND_DIST at the bundle built for this mode."
        )
    return None


def _set_viewer_env(project_root: Path, bundle_root: Path, args: argparse.Namespace) -> None:
    if not args.viewer:
        return

    os.environ["COPYLOT_VIEWER_MODE"] = "1"
    if args.project:
        os.environ["COPYLOT_VIEWER_PROJECT"] = args.project

    if args.viewer_config:
        os.environ["COPYLOT_VIEWER_CONFIG"] = str(Path(args.viewer_config).resolve())
        return

    if args.project:
        resolved = _resolve_viewer_project_config(project_root, bundle_root, args.project)
        if resolved is None:
            searched = "\n".join(
                f"- {candidate}" for candidate in _viewer_project_config_candidates(project_root, bundle_root, args.project)
            )
            raise FileNotFoundError(
                f"Viewer project '{args.project}' not found or has no config file.\n"
                f"Searched:\n{searched}"
            )
        os.environ["COPYLOT_VIEWER_CONFIG"] = str(resolved)
        return

    candidates = [
        project_root / "local" / "viewer_config.local.json",
        project_root / "viewer_config.local.json",
        bundle_root / "local" / "viewer_config.local.json",
        bundle_root / "viewer_config.local.json",
        project_root / "viewer_config.json",
        bundle_root / "viewer_config.json",
    ]
    for candidate in candidates:
        if candidate.is_file():
            os.environ["COPYLOT_VIEWER_CONFIG"] = str(candidate)
            return

    projects = _discover_viewer_projects(project_root, bundle_root)
    if len(projects) == 1:
        project_name = projects[0]
        resolved = _resolve_viewer_project_config(project_root, bundle_root, project_name)
        if resolved is not None:
            os.environ["COPYLOT_VIEWER_PROJECT"] = project_name
            os.environ["COPYLOT_VIEWER_CONFIG"] = str(resolved)
            return


def _open_browser_later(url: str) -> None:
    def _open() -> None:
        webbrowser.open(url)

    timer = threading.Timer(1.5, _open)
    timer.daemon = True
    timer.start()


def _set_ai_mode_from_executable_name() -> None:
    # Keep explicit user/system configuration authoritative.
    if str(os.getenv("COPYLOT_AI_MODE", "")).strip():
        return
    if not getattr(sys, "frozen", False):
        return

    stem = Path(sys.executable).stem.lower()
    if stem.endswith("ai"):
        os.environ["COPYLOT_AI_MODE"] = "1"


def _normalize_project_name(raw: str) -> str:
    value = str(raw or "").strip()
    if value.startswith("--"):
        value = value[2:].strip()
    if not value:
        raise ValueError("Viewer project name is empty.")
    if not _PROJECT_NAME_RE.fullmatch(value):
        raise ValueError(
            "Invalid viewer project name. Allowed characters: letters, numbers, dot, underscore, hyphen."
        )
    return value


def _viewer_project_dirs(project_root: Path, bundle_root: Path, project_name: str) -> list[Path]:
    return [
        project_root / "viewer_data" / "local" / project_name,
        project_root / "viewer_data" / project_name,
        project_root / "viewer_data" / "projects" / project_name,
        bundle_root / "viewer_data" / "local" / project_name,
        bundle_root / "viewer_data" / project_name,
        bundle_root / "viewer_data" / "projects" / project_name,
    ]


def _viewer_project_config_candidates(project_root: Path, bundle_root: Path, project_name: str) -> list[Path]:
    candidates: list[Path] = []
    for base in _viewer_project_dirs(project_root, bundle_root, project_name):
        candidates.extend(
            [
                base / "viewer_config.local.json",
                base / "viewer_config.json",
            ]
        )
    return candidates


def _resolve_viewer_project_config(project_root: Path, bundle_root: Path, project_name: str) -> Path | None:
    for candidate in _viewer_project_config_candidates(project_root, bundle_root, project_name):
        if candidate.is_file():
            return candidate
    return None


def _discover_viewer_projects(project_root: Path, bundle_root: Path) -> list[str]:
    roots = [
        project_root / "viewer_data" / "local",
        project_root / "viewer_data",
        project_root / "viewer_data" / "projects",
        bundle_root / "viewer_data" / "local",
        bundle_root / "viewer_data",
        bundle_root / "viewer_data" / "projects",
    ]
    out: set[str] = set()
    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        for child in root.iterdir():
            if not child.is_dir():
                continue
            name = child.name
            if not _PROJECT_NAME_RE.fullmatch(name):
                continue
            if (child / "viewer_config.local.json").is_file() or (child / "viewer_config.json").is_file():
                out.add(name)
    return sorted(out)


def _parse_shorthand_project_arg(unknown_args: list[str]) -> tuple[str, list[str]]:
    project = ""
    remaining: list[str] = []
    for token in unknown_args:
        stripped = str(token).strip()
        if not stripped:
            continue
        candidate = stripped
        if candidate.startswith("--"):
            if candidate == "--":
                remaining.append(token)
                continue
            candidate = candidate[2:]
        elif candidate.startswith("-"):
            remaining.append(token)
            continue
        try:
            normalized = _normalize_project_name(candidate)
        except ValueError:
            remaining.append(token)
            continue
        if project and normalized != project:
            remaining.append(token)
            continue
        project = normalized
    return project, remaining


def main() -> None:
    parser = argparse.ArgumentParser(description="Start Proteomics CoPYlot")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--viewer", action="store_true")
    parser.add_argument("--viewer-config", default="")
    parser.add_argument("--project", default="")
    parser.add_argument("--list-projects", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument(
        "--allow-unsafe-public",
        action="store_true",
        help="Allow an unauthenticated non-loopback bind after printing a security warning.",
    )
    args, unknown_args = parser.parse_known_args()

    explicit_project = ""
    if args.project:
        try:
            explicit_project = _normalize_project_name(args.project)
        except ValueError as exc:
            parser.error(str(exc))

    shorthand_project = ""
    remaining_unknown = unknown_args
    if args.viewer or args.list_projects:
        shorthand_project, remaining_unknown = _parse_shorthand_project_arg(unknown_args)
        if explicit_project and shorthand_project and explicit_project != shorthand_project:
            parser.error(
                f"Conflicting project names: --project {explicit_project} and shorthand {shorthand_project}"
            )
        args.project = explicit_project or shorthand_project
    elif explicit_project:
        parser.error("--project can only be used together with --viewer.")
    else:
        args.project = ""

    if remaining_unknown:
        parser.error(f"Unrecognized arguments: {' '.join(remaining_unknown)}")

    project_root = _project_root()
    bundle_root = _bundle_root()
    if args.list_projects:
        projects = _discover_viewer_projects(project_root, bundle_root)
        if not projects:
            print("No viewer projects found.")
        else:
            print("\n".join(projects))
        return

    _set_ai_mode_from_executable_name()
    _ensure_backend_on_path(project_root, bundle_root)
    _set_frontend_dist_env(project_root, bundle_root)
    _set_viewer_env(project_root, bundle_root, args)
    try:
        warning = check_frontend_bundle_mode(viewer_mode_requested(bool(args.viewer)))
    except ValueError as exc:
        parser.error(str(exc))
    if warning:
        print(f"Warning: {warning}", file=sys.stderr)
    try:
        _validate_network_binding(
            args.host,
            allow_unsafe_public=args.allow_unsafe_public,
        )
    except ValueError as exc:
        parser.error(str(exc))

    if not args.no_browser:
        _open_browser_later(f"http://{args.host}:{args.port}")

    import uvicorn
    from app.main import app as fastapi_app

    # Use direct app object import so bundled onefile executables do not rely on
    # uvicorn's dynamic string import resolution at runtime.
    uvicorn.run(
        fastapi_app,
        # Session and analysis stores are process-local; ignore WEB_CONCURRENCY.
        workers=1,
        host=args.host,
        port=args.port,
        log_level="info",
        server_header=False,
        forwarded_allow_ips=str(os.getenv("COPYLOT_TRUSTED_PROXY_IPS", "127.0.0.1")),
    )


if __name__ == "__main__":
    main()
