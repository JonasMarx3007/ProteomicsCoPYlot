from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_documented_repository_directories_exist() -> None:
    for relative in (
        "backend",
        "frontend",
        "proteomicscopylot",
        "tests",
        "examples",
        "docs",
        "packaging/windows",
        "packaging/macos",
        "packaging/linux",
        "packaging/python",
    ):
        assert (ROOT / relative).is_dir(), relative


def test_root_has_no_legacy_clutter() -> None:
    legacy_names = {
        "readme.txt",
        "example.ipynb",
        "example.R",
        "example_data",
        "scripts",
        "favicon.ico",
        "run_app.bat",
        "run_viewer.bat",
        "build_exe_windows.ps1",
        "build_pip_package.py",
    }
    assert not {name for name in legacy_names if (ROOT / name).exists()}


def test_platform_launchers_reference_repository_root() -> None:
    windows = (ROOT / "packaging" / "windows" / "run_app.bat").read_text(encoding="utf-8")
    linux = (ROOT / "packaging" / "linux" / "run_app_linux.sh").read_text(encoding="utf-8")
    macos = (ROOT / "packaging" / "macos" / "run_app_macos.sh").read_text(encoding="utf-8")
    assert "%SCRIPT_DIR%..\\.." in windows
    assert '$(dirname "${BASH_SOURCE[0]}")/../..' in linux
    assert '$(dirname "${BASH_SOURCE[0]}")/../..' in macos


def test_project_guidance_files_exist() -> None:
    for relative in ("README.md", "docs/INSTALLATION.md", "docs/ARCHITECTURE.md"):
        assert (ROOT / relative).is_file(), relative


def test_packaging_includes_canonical_example_data() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    windows_build = (ROOT / "packaging" / "windows" / "build_exe_windows.ps1").read_text(encoding="utf-8")
    macos_build = (ROOT / "packaging" / "macos" / "build_all_macos_variants.sh").read_text(encoding="utf-8")
    assert "COPY proteomicscopylot/example_data" in dockerfile
    assert "proteomicscopylot\\example_data" in windows_build
    assert "proteomicscopylot/example_data:proteomicscopylot/example_data" in macos_build


def test_executable_builds_exclude_private_viewer_data() -> None:
    windows_build = (ROOT / "packaging" / "windows" / "build_exe_windows.ps1").read_text(
        encoding="utf-8"
    )
    macos_build = (
        ROOT / "packaging" / "macos" / "build_all_macos_variants.sh"
    ).read_text(encoding="utf-8")

    assert '$(Join-Path $RootDir "viewer_data");viewer_data' not in windows_build
    assert '--add-data "viewer_data:viewer_data"' not in macos_build
    assert "viewer_data\\local" not in windows_build
    assert "viewer_data\\projects" not in windows_build
    assert "git -C $RootDir ls-files" in windows_build
    assert "viewer_config.local.json" not in windows_build
    assert ".local." in windows_build
    assert "viewer_access.json" in windows_build


def test_example_notebook_is_bom_free_valid_json() -> None:
    notebook_path = ROOT / "examples" / "example.ipynb"
    raw = notebook_path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    payload = json.loads(raw.decode("utf-8"))
    assert payload["nbformat"] == 4
    assert payload["cells"]


def test_local_markdown_links_resolve() -> None:
    ignored_parts = {
        ".git",
        ".pytest_cache",
        ".venv",
        "build",
        "dist",
        "local",
        "node_modules",
    }
    markdown_files = [
        path
        for path in ROOT.rglob("*.md")
        if not ignored_parts.intersection(path.relative_to(ROOT).parts)
    ]
    broken: list[str] = []
    for markdown in markdown_files:
        text = markdown.read_text(encoding="utf-8")
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
            target = target.strip().split("#", 1)[0]
            if not target or target.startswith(("#", "http://", "https://", "mailto:")):
                continue
            resolved = (markdown.parent / target).resolve()
            if not resolved.exists():
                broken.append(f"{markdown.relative_to(ROOT)} -> {target}")
    assert not broken, "Broken local Markdown links:\n" + "\n".join(broken)
