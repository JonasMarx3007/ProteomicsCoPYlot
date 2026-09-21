from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = ROOT / "packaging" / "python" / "build_pip_package.py"


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
        "release/python/1.0.0/package.whl",
    ]
    visible = [
        ".env.example",
        "server.example.key",
        "migrations/001_initial.sql",
        "data/db/reference.db",
    ]
    assert all(_ignored(path) for path in ignored)
    assert not any(_ignored(path) for path in visible)


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
    assert output == (ROOT / "release" / "python" / version).resolve()
    assert output.parent == (ROOT / "release" / "python").resolve()


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
