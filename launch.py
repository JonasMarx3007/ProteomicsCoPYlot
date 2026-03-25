from __future__ import annotations

import argparse
import os
import sys
import threading
import webbrowser
from pathlib import Path


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
    if args.viewer_config:
        os.environ["COPYLOT_VIEWER_CONFIG"] = str(Path(args.viewer_config).resolve())
        return

    candidates = [
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Start Proteomics CoPYlot")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--viewer", action="store_true")
    parser.add_argument("--viewer-config", default="")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    project_root = _project_root()
    bundle_root = _bundle_root()
    _ensure_backend_on_path(project_root, bundle_root)
    _set_frontend_dist_env(project_root, bundle_root)
    _set_viewer_env(project_root, bundle_root, args)

    if not args.no_browser:
        _open_browser_later(f"http://{args.host}:{args.port}")

    import uvicorn

    uvicorn.run("app.main:app", host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
