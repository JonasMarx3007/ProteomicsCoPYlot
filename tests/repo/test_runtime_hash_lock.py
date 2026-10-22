"""Runtime artifact hashes must never silently change the reviewed versions."""
import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("hash_runtime_requirements", ROOT / "tools/hash_runtime_requirements.py")
hash_tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hash_tool)


def test_hash_lock_covers_exactly_the_runtime_pins():
    pins = hash_tool.read_pins(hash_tool.PINS.read_text(encoding="utf-8"))
    hashed = hash_tool.HASHED.read_text(encoding="utf-8").replace("\\\n", " ")
    found = []
    for line in hashed.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split()
        found.append(tuple(parts[0].split("==")))
        assert len(parts) > 1
        assert all(re.fullmatch(r"--hash=sha256:[a-f0-9]{64}", part) for part in parts[1:])
    assert found == pins


def test_hash_generation_keeps_versions_and_rejects_missing_artifacts():
    release = {"info": {"version": "1.0"}, "urls": [
        {"yanked": False, "digests": {"sha256": "a" * 64}},
        {"yanked": True, "digests": {"sha256": "b" * 64}},
    ]}
    result = hash_tool.render([("example", "1.0")], {"example": release})
    assert "example==1.0" in result and "sha256:" + "a" * 64 in result
    assert "sha256:" + "b" * 64 not in result
    with pytest.raises(ValueError, match="Unexpected release"):
        hash_tool.render([("example", "2.0")], {"example": release})
    release["urls"] = []
    with pytest.raises(ValueError, match="No valid"):
        hash_tool.render([("example", "1.0")], {"example": release})


def test_release_installs_enforce_hashes():
    for path in (ROOT / "Dockerfile", ROOT / ".github/workflows/macos-release.yml"):
        text = path.read_text(encoding="utf-8")
        assert "pip install --require-hashes" in text
        assert "-r " in text and "requirements-runtime-hashed.lock" in text
    assert "pip install --upgrade pip" not in (ROOT / "Dockerfile").read_text(encoding="utf-8")
