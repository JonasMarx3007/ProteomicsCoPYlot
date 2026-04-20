from __future__ import annotations

import argparse
import os
import re
import sys
import threading
import webbrowser
from pathlib import Path

_PROJECT_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


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
        project_root / "viewer_config.local.json",
        bundle_root / "viewer_config.local.json",
        project_root / "viewer_config.json",
        bundle_root / "viewer_config.json",
    ]
    for candidate in candidates:
        if candidate.is_file():
            os.environ["COPYLOT_VIEWER_CONFIG"] = str(candidate)
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
    if stem.endswith("ai") or "aidev" in stem:
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
        project_root / "viewer_data" / project_name,
        project_root / "viewer_data" / "projects" / project_name,
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
        project_root / "viewer_data",
        project_root / "viewer_data" / "projects",
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

    if not args.no_browser:
        _open_browser_later(f"http://{args.host}:{args.port}")

    import uvicorn
    from app.main import app as fastapi_app

    # Use direct app object import so bundled onefile executables do not rely on
    # uvicorn's dynamic string import resolution at runtime.
    uvicorn.run(fastapi_app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
