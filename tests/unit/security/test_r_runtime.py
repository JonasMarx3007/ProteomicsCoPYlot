from __future__ import annotations

from app.services.r_runtime import _parse_r_version, clear_r_runtime_cache, detect_r_runtime


def test_r_version_parser() -> None:
    assert _parse_r_version("Rscript (R) version 4.5.1 (2025-06-13)") == "4.5.1"
    assert _parse_r_version("unrecognized output") is None


def test_runtime_probe_has_stable_shape() -> None:
    clear_r_runtime_cache()
    payload = detect_r_runtime()
    assert isinstance(payload["available"], bool)
    assert isinstance(payload["candidates"], list)
    assert payload["detectedFrom"] in {None, "env", "path", "common_path"}
