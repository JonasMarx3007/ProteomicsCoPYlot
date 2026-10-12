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
        "packaging/unix",
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
    unix = (ROOT / "packaging" / "unix" / "run_app.sh").read_text(encoding="utf-8")
    assert "%SCRIPT_DIR%..\\.." in windows
    assert '$(dirname "${BASH_SOURCE[0]}")/../..' in unix


def test_project_guidance_files_exist() -> None:
    for relative in (
        "README.md",
        "CHANGELOG.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "docs/INSTALLATION.md",
        "docs/ARCHITECTURE.md",
    ):
        assert (ROOT / relative).is_file(), relative


def test_project_versions_agree() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    version = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.M).group(1)

    citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    cited = re.search(r'^version:\s*"?([^"\n]+)"?', citation, re.M).group(1).strip()
    assert cited == version, f"CITATION.cff says {cited}, pyproject says {version}"

    for relative, name in (
        ("backend/app/app_version.py", "APP_VERSION"),
        ("proteomicscopylot/_version.py", "__version__"),
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        declared = re.search(rf'^\s*{name}\s*=\s*"([^"]+)"', source, re.M).group(1)
        assert declared == version, relative

    from proteomicscopylot import __version__

    assert __version__ == version

    package = json.loads((ROOT / "frontend/package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "frontend/package-lock.json").read_text(encoding="utf-8"))
    assert package["version"] == lock["version"] == lock["packages"][""]["version"] == version


def test_react_and_react_dom_versions_agree() -> None:
    package = json.loads((ROOT / "frontend/package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "frontend/package-lock.json").read_text(encoding="utf-8"))
    assert package["dependencies"]["react"] == package["dependencies"]["react-dom"]
    packages = lock["packages"]
    assert packages["node_modules/react"]["version"] == packages["node_modules/react-dom"]["version"]


def test_packaging_includes_canonical_example_data() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    windows_build = (ROOT / "packaging" / "windows" / "build_exe_windows.ps1").read_text(encoding="utf-8")
    macos_build = (ROOT / "packaging" / "macos" / "build_all_macos_variants.sh").read_text(encoding="utf-8")
    assert "COPY proteomicscopylot/example_data" in dockerfile
    assert "proteomicscopylot\\example_data" in windows_build
    assert "proteomicscopylot/example_data:proteomicscopylot/example_data" in macos_build


def test_docker_frontend_build_has_project_licence_inputs() -> None:
    frontend_stage = (ROOT / "Dockerfile").read_text(encoding="utf-8").split("FROM python:", 1)[0]
    assert "COPY LICENSE NOTICE /build/" in frontend_stage
    assert frontend_stage.index("COPY LICENSE NOTICE /build/") < frontend_stage.index("RUN npm run build")


def test_deployment_and_reference_ci_use_exact_dependency_locks() -> None:
    runtime_lock = ROOT / "backend" / "requirements-runtime.lock"
    development_lock = ROOT / "backend" / "requirements.lock"
    assert runtime_lock.is_file()
    assert development_lock.is_file()

    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    security = (ROOT / ".github" / "workflows" / "security.yml").read_text(encoding="utf-8")
    tests = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    parity = (ROOT / ".github" / "workflows" / "cross-implementation.yml").read_text(
        encoding="utf-8"
    )

    assert "COPY backend/requirements-runtime.lock" in dockerfile
    assert "FROM python:3.13-" in dockerfile
    assert "pip install -r /app/backend/requirements-runtime.lock" in dockerfile
    assert "pip_audit --requirement backend/requirements-runtime.lock" in security
    assert "pip_audit --requirement backend/requirements.lock" in security
    assert "pip install -r backend/requirements.lock" in tests
    assert "pip install -r backend/requirements.lock" in parity

    def locked_versions(path: Path) -> dict[str, str]:
        versions: dict[str, str] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            requirement = line.strip()
            if not requirement or requirement.startswith("#"):
                continue
            name, version = requirement.split("==", 1)
            versions[name.lower().replace("_", "-")] = version
        return versions

    runtime_versions = locked_versions(runtime_lock)
    development_versions = locked_versions(development_lock)
    assert runtime_versions.items() <= development_versions.items()


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


def test_launchers_and_builders_have_no_development_presets() -> None:
    for path in (ROOT / "packaging").rglob("*"):
        if not path.is_file() or path.suffix not in {".sh", ".bat", ".cmd", ".ps1", ".py", ""}:
            continue
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"AIDev|DEV_MODE|DEV20_ENDPOINT|dev_ai\.local|--dev(?:0|2|20)?\b", text), path
    for platform, name in [("windows", "build_all_windows_variants.cmd"), ("macos", "build_all_macos_variants.sh")]:
        text = (ROOT / "packaging" / platform / name).read_text(encoding="utf-8")
        for variant in ("ProteomicsCoPYlot", "ProteomicsCoPYlotAI", "DataViewer", "DataViewerAI"):
            assert variant in text
        assert "[4/4]" in text and "/6]" not in text
    for platform, suffix in [("windows", ".bat"), ("unix", ".sh")]:
        for mode in ("app", "viewer"):
            text = (ROOT / "packaging" / platform / f"run_{mode}_ai{suffix}").read_text(encoding="utf-8")
            assert "uvicorn app.main:app" in text and "npm run dev" in text
            assert "COPYLOT_AI_MODE=1" in text and "VITE_AI_ENABLED=1" in text


def test_viewer_launchers_enable_isolation_and_windows_launchers_check_ports() -> None:
    for platform in ("windows", "unix"):
        for path in (ROOT / "packaging" / platform).glob("run_viewer*"):
            text = path.read_text(encoding="utf-8")
            assert "COPYLOT_SESSION_ISOLATION=1" in text
            assert "COPYLOT_SESSION_ISOLATION=0" not in text
    for path in (ROOT / "packaging" / "windows").glob("run*.bat"):
        text = path.read_text(encoding="utf-8")
        assert "Stop-Process" not in text and "taskkill" not in text.lower()
        assert text.index("check_launch_ports.ps1") < text.index('start "')
        assert "if errorlevel 1 exit /b 1" in text


def test_windows_port_check_preserves_existing_listeners() -> None:
    import os
    import socket
    import subprocess
    import pytest

    if os.name != "nt":
        pytest.skip("Windows launcher check")
    with socket.socket() as backend, socket.socket() as frontend:
        backend.bind(("127.0.0.1", 0))
        frontend.bind(("127.0.0.1", 0))
        ports = [backend.getsockname()[1], frontend.getsockname()[1]]
        def check():
            return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                str(ROOT / "packaging/windows/check_launch_ports.ps1"),
                "-BackendPort", str(ports[0]), "-FrontendPort", str(ports[1])],
                # Cold PowerShell startup on hosted Windows can exceed 20 seconds.
                capture_output=True, text=True, timeout=60)
        assert check().returncode == 0
        for listener, port in zip((backend, frontend), ports):
            listener.listen()
            result = check()
            assert result.returncode == 1 and str(port) in result.stdout
            assert "No existing processes were stopped" in result.stdout
            with socket.create_connection(("127.0.0.1", port), timeout=2):
                connection, _ = listener.accept()
                connection.close()


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


def test_build_scripts_import_names_that_exist() -> None:
    """Inline Python in build files is not linted, so a moved function breaks only the build."""
    import ast

    sources = [ROOT / "Dockerfile", *sorted((ROOT / "packaging").rglob("*.sh")),
               *sorted((ROOT / "packaging").rglob("*.ps1")), *sorted((ROOT / ".github").rglob("*.yml"))]
    pattern = re.compile(r"from (app(?:\.\w+)+) import ([\w, ]+)")
    checked = 0
    for source in sources:
        for module, names in pattern.findall(source.read_text(encoding="utf-8")):
            path = ROOT / "backend" / Path(*module.split("."))
            path = path / "__init__.py" if path.is_dir() else path.with_suffix(".py")
            assert path.is_file(), f"{source.name}: module {module} does not exist"
            tree = ast.parse(path.read_text(encoding="utf-8"))
            defined = {node.name for node in tree.body
                       if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
            defined |= {target.id for node in tree.body if isinstance(node, ast.Assign)
                        for target in node.targets if isinstance(target, ast.Name)}
            defined |= {alias.asname or alias.name for node in tree.body
                        if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names}
            for name in (part.strip() for part in names.split(",")):
                assert name in defined, f"{source.name}: {module} has no {name}"
                checked += 1
    assert checked, "expected at least the Dockerfile font check"


def test_ai_gated_browser_tests_are_tagged_for_ci() -> None:
    """CI runs the AI-gated browser tests by their @ai tag; an untagged one would never run there."""
    gate = re.compile(r"test\.skip\(process\.env\.(?:VITE_AI_ENABLED|COPYLOT_BROWSER_ASSISTANT_STUB) !== '1'")
    declaration = re.compile(r"\btest\((['`]).*?\1,")
    for spec in sorted((ROOT / "frontend" / "tests" / "browser").glob("*.spec.mjs")):
        lines = spec.read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(lines):
            if not gate.search(line):
                continue
            owner = next(lines[i] for i in range(number - 1, -1, -1) if declaration.search(lines[i]))
            assert "tag: '@ai'" in owner, f"{spec.name}:{number + 1} is AI-gated but not tagged @ai"
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert 'npx playwright test --grep "@ai' in workflow


def test_unix_launchers_open_the_browser_on_macos_and_linux() -> None:
    """One launcher set serves macOS and Linux; only the browser opener differs."""
    for path in (ROOT / "packaging" / "unix").glob("run_*.sh"):
        text = path.read_text(encoding="utf-8")
        assert 'if [ "$(uname -s)" = "Darwin" ]; then' in text and "xdg-open" in text, path
        assert 'open_browser "http://localhost:' in text, path
    assert not (ROOT / "packaging" / "linux").exists()
    assert not list((ROOT / "packaging" / "macos").glob("run_*"))
