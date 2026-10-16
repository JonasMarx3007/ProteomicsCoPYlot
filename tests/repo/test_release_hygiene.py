from __future__ import annotations

import importlib.util
import json
import re
import runpy
import subprocess
from pathlib import Path

import pytest
from packaging.version import Version


ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = ROOT / "packaging" / "python" / "build_pip_package.py"


def test_application_version_is_consistent_across_release_metadata():
    from proteomicscopylot import __version__
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    expected = re.search(r'^version = "([^"]+)"$', project, re.M).group(1)
    frontend = json.loads((ROOT / "frontend/package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "frontend/package-lock.json").read_text(encoding="utf-8"))
    citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    versions = {
        "public package version": __version__,
        "backend": runpy.run_path(str(ROOT / "backend/app/app_version.py"))["APP_VERSION"],
        "python package": runpy.run_path(str(ROOT / "proteomicscopylot/_version.py"))["__version__"],
        "frontend": frontend["version"],
        "lockfile": lock["version"],
        "lockfile root package": lock["packages"][""]["version"],
        "citation": re.search(r'^version: "([^"]+)"$', citation, re.M).group(1),
        "OpenAPI snapshot": json.loads(
            (ROOT / "frontend/src/lib/generated/openapi.json").read_text(encoding="utf-8")
        )["info"]["version"],
    }
    assert all(Version(value) == Version(expected) for value in versions.values()), versions


def test_the_package_the_citation_and_the_license_name_the_same_author():
    """What PyPI shows, what a paper cites and who holds the copyright are one person, spelled once."""
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    # Read with a pattern rather than tomllib, which Python 3.10 lacks.
    authors_block = re.search(r"^authors = \[(.*?)^\]", project, re.M | re.S).group(1)
    package_authors = re.findall(r'name = "([^"]+)"', authors_block)
    citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    block = citation.split("\nauthors:\n", 1)[1].split("\nreferences:", 1)[0]
    cited = [
        f"{given} {family}"
        for family, given in re.findall(r'family-names: "([^"]+)"\s+given-names: "([^"]+)"', block)
    ]
    assert package_authors == cited, (package_authors, cited)
    # The GPL text credits the FSF; project copyright belongs in NOTICE.
    holder = re.search(r"^Copyright \(c\) \d{4}(?:-\d{4})? (.+)$", (ROOT / "NOTICE").read_text(encoding="utf-8"), re.M)
    assert holder and [holder.group(1).strip()] == cited, (holder and holder.group(1), cited)


def _load_build_script():
    spec = importlib.util.spec_from_file_location("build_pip_package", BUILD_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ignored(path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", "--", path],
        cwd=ROOT,
        check=False,
    )
    return result.returncode == 0


def test_secret_and_local_artifact_ignore_contract() -> None:
    ignored = [
        ".env",
        ".env.production",
        "private/server.key",
        "backup.sql",
        "cache.sqlite3",
        "release/python/1.0.0-beta.1/package.whl",
    ]
    visible = [
        ".env.example",
        "server.example.key",
        "migrations/001_initial.sql",
        "data/db/reference.db",
    ]
    assert all(_ignored(path) for path in ignored)
    assert not any(_ignored(path) for path in visible)


def test_default_test_discovery_excludes_local_scratch(pytestconfig) -> None:
    assert pytestconfig.getini("testpaths") == ["tests"]


def test_api_documentation_uses_the_application_version() -> None:
    from app.app_version import APP_VERSION
    from app.main import app

    assert app.version == APP_VERSION
    assert app.openapi()["info"]["version"] == APP_VERSION


def test_release_artifact_set_is_exact_and_versioned(tmp_path: Path) -> None:
    build_script = _load_build_script()
    version = build_script.project_version()
    expected = build_script.expected_artifact_names(version)
    for name in expected:
        (tmp_path / name).write_bytes(b"package")

    artifacts = build_script.validate_artifact_set(tmp_path, version)
    assert {path.name for path in artifacts} == expected

    (tmp_path / "proteomicscopylot-0.1.0.tar.gz").write_bytes(b"stale")
    with pytest.raises(RuntimeError, match="unexpected"):
        build_script.validate_artifact_set(tmp_path, version)


def test_release_output_is_version_scoped() -> None:
    build_script = _load_build_script()
    version = build_script.project_version()
    output = build_script.release_output_dir(version)
    frontend = json.loads((ROOT / "frontend/package.json").read_text(encoding="utf-8"))
    assert output == (ROOT / "release" / "python" / frontend["version"]).resolve()
    assert output.parent == (ROOT / "release" / "python").resolve()


@pytest.mark.parametrize("version,label", [
    ("1.0.0b1", "1.0.0-beta.1"),
    ("1.0.0b21", "1.0.0-beta.21"),
    ("1.0.0", "1.0.0"),
    ("1.0.1", "1.0.1"),
])
def test_release_label_preserves_beta_sequence(version: str, label: str) -> None:
    assert _load_build_script().release_label(version) == label


def test_release_build_cleans_only_managed_python_output(
    monkeypatch,
    tmp_path: Path,
) -> None:
    build_script = _load_build_script()
    release_root = tmp_path / "release" / "python"
    stale = release_root / "0.1.0" / "stale.whl"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"stale")
    monkeypatch.setattr(build_script, "RELEASE_ROOT", release_root)

    output = build_script.release_output_dir("1.0.0")
    build_script.prepare_release_output(output)

    assert output.is_dir()
    assert not stale.exists()
    assert tmp_path.is_dir()
