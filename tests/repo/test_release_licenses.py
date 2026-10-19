from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from tools import package_release_licenses as release


def test_project_license_and_credits_are_consistent():
    root = release.ROOT
    assert "GNU GENERAL PUBLIC LICENSE" in (root / "LICENSE").read_text()
    notice = (root / "NOTICE").read_text(encoding="utf-8")
    for author in ("Jonas Marx", "Alexander Hogrebe", "Denys Oliinyk", "Yue Yang"):
        assert author in notice
    assert 'license: "GPL-3.0-only"' in (root / "CITATION.cff").read_text()
    assert 'license = "GPL-3.0-only AND CC-BY-4.0"' in (root / "pyproject.toml").read_text()
    assert json.loads((root / "frontend/package.json").read_text())["license"] == "GPL-3.0-only"
    assert "license: { fileName:" in (root / "frontend/vite.config.ts").read_text()
    for path in ("packaging/windows/build_exe_windows.ps1", "packaging/macos/build_all_macos_variants.sh"):
        text = (root / path).read_text()
        assert "package_release_licenses.py" in text
        assert " prepare --legal-dir" in text and " finish --legal-dir" in text
        assert "NOTICE" in text


def test_collector_keeps_native_notices_and_rejects_a_license_identifier_only(tmp_path):
    folder = tmp_path / "pkg.dist-info/licenses"
    folder.mkdir(parents=True)
    (folder / "LICENSE.txt").write_text("An upstream licence")
    (folder / "NOTICE").write_text("A native library copyright")
    distribution = SimpleNamespace(
        files=[Path("pkg.dist-info/licenses/LICENSE.txt"), Path("pkg.dist-info/licenses/NOTICE")],
        metadata={"Name": "pkg", "License": "MIT"}, locate_file=lambda p: tmp_path / p)
    texts = release.license_texts(distribution)
    assert [text for _, text in texts] == ["An upstream licence", "A native library copyright"]
    distribution.files = []
    with pytest.raises(ValueError, match="No licence text"):
        release.license_texts(distribution)


def test_dirty_source_is_not_presented_as_a_matching_release(monkeypatch, tmp_path):
    monkeypatch.setattr(release, "git", lambda *args: b" M source.py\n")
    with pytest.raises(ValueError, match="Commit the reviewed source"):
        release.clean_revision(tmp_path)


def test_conda_native_licenses_and_python_fallback(monkeypatch, tmp_path):
    cache = tmp_path / "cache/llvmlite/info/licenses"
    cache.mkdir(parents=True)
    (cache / "LICENSE").write_text("llvmlite licence")
    (cache / "LICENSE.thirdparty").write_text("LLVM licence")
    records = tmp_path / "env/conda-meta"
    records.mkdir(parents=True)
    (records / "llvmlite.json").write_text(json.dumps({
        "name": "llvmlite", "version": "0.49.0", "build": "test",
        "files": ["lib/libllvmlite.dylib"], "link": {"source": str(cache.parent.parent)},
    }))
    monkeypatch.setattr(release.sys, "prefix", str(records.parent))
    distribution = SimpleNamespace(files=[], metadata={"Name": "llvmlite", "License": "BSD"})
    assert [text for _, text in release.license_texts(distribution)] == ["llvmlite licence", "LLVM licence"]
    (cache / "LICENSE").unlink()
    (cache / "LICENSE.thirdparty").unlink()
    with pytest.raises(ValueError, match="Missing Conda licence"):
        release.conda_licenses(records.parent)


def test_no_conda_environment_has_no_extra_notices(tmp_path):
    assert release.conda_licenses(tmp_path) == []


@pytest.mark.parametrize("path", ["source/local/private.csv", "source/.env", "source/../private"])
def test_source_archive_rejects_private_paths(monkeypatch, tmp_path, path):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(path, "not public")
    monkeypatch.setattr(release, "git", lambda *args: stream.getvalue())
    with pytest.raises(ValueError, match="Private or generated"):
        release.source_archive(tmp_path)


def test_release_zip_contains_exact_source_notices_and_binary(monkeypatch, tmp_path):
    legal = tmp_path / "legal"
    legal.mkdir()
    for name in ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.txt", "README.txt", "build-requirements.txt"):
        (legal / name).write_text(name)
    source = b"matching source archive"
    (legal / "CoPYlot-source.zip").write_bytes(source)
    (legal / "release-manifest.json").write_text(json.dumps(
        {"revision": "tested", "source_sha256": hashlib.sha256(source).hexdigest()}))
    binary = tmp_path / "CoPYlot.exe"
    binary.write_bytes(b"signed executable")
    monkeypatch.setattr(release, "clean_revision", lambda root: "tested")
    output = release.finish(tmp_path, legal, binary)
    with zipfile.ZipFile(output) as archive:
        assert archive.read("CoPYlot.exe") == binary.read_bytes()
        assert archive.read("CoPYlot-source.zip") == source
        assert archive.read("NOTICE") == b"NOTICE"
        manifest = json.loads(archive.read("release-manifest.json"))
        assert manifest["executable_sha256"] == hashlib.sha256(binary.read_bytes()).hexdigest()
    monkeypatch.setattr(release, "clean_revision", lambda root: "different")
    with pytest.raises(ValueError, match="Source changed"):
        release.finish(tmp_path, legal, binary)
    monkeypatch.setattr(release, "clean_revision", lambda root: "tested")
    (legal / "CoPYlot-source.zip").write_bytes(b"different source")
    with pytest.raises(ValueError, match="source archive changed"):
        release.finish(tmp_path, legal, binary)
