"""The certificate fixture must respect Linux bind-mount ownership."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

spec = importlib.util.spec_from_file_location(
    "docker_runtime_check", Path(__file__).parents[1] / "docker_runtime_check.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


@pytest.mark.parametrize("platform", ["posix", "nt"])
def test_certificate_uses_host_owner_only_on_posix(monkeypatch, tmp_path, platform):
    runner = Mock()
    monkeypatch.setattr(runtime, "docker", runner)
    monkeypatch.setattr(runtime, "os", SimpleNamespace(name=platform, getuid=lambda: 1001, getgid=lambda: 1002))
    runtime.create_certificate("test-image", tmp_path)
    args = runner.call_args.args
    assert args[:4] == ("run", "--rm", "--network", "none")
    assert f"type=bind,source={tmp_path},target=/check" in args
    if platform == "posix":
        assert args[args.index("--user") + 1] == "1001:1002"
    else:
        assert "--user" not in args


def test_docker_failure_exposes_stderr(monkeypatch):
    monkeypatch.setattr(runtime.subprocess, "run", Mock(return_value=SimpleNamespace(
        returncode=1, stdout="", stderr="Permission denied")))
    with pytest.raises(RuntimeError, match="Permission denied"):
        runtime.docker("run", "test-image")
