"""Launchers must override inherited concurrency while stores are in memory."""
import ast
import importlib
from pathlib import Path
import re

from click.testing import CliRunner
import pytest
import uvicorn

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = [ROOT / "packaging" / platform / f"run_{mode}{suffix}"
           for platform, suffix in [("windows", ".bat"), ("unix", ".sh")]
           for mode in ("app", "app_ai", "viewer", "viewer_ai")]


@pytest.mark.parametrize("path", SCRIPTS, ids=lambda path: f"{path.parent.name}/{path.name}")
def test_cli_launchers_override_environment(monkeypatch, path):
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    main = importlib.import_module("uvicorn.main")
    configured_workers = []

    def capture(app, **kwargs):
        configured_workers.append(uvicorn.Config(app, workers=kwargs["workers"]).workers)

    monkeypatch.setattr(main, "run", capture)
    commands = [line for line in path.read_text().splitlines() if "-m uvicorn " in line]
    assert commands
    for command in commands:
        flags = re.findall(r"--workers(?:\s+|=)(\d+)\b", command)
        assert flags == ["1"], command
        result = CliRunner().invoke(main.main, ["app.main:app", "--workers", flags[0]])
        assert result.exit_code == 0, result.output
    assert configured_workers == [1] * len(commands)


def test_packaged_and_docker_launcher_overrides_environment(monkeypatch):
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    tree = ast.parse((ROOT / "launch.py").read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
             and node.func.value.id == "uvicorn" and node.func.attr == "run"]
    assert len(calls) == 1
    workers = next(ast.literal_eval(k.value) for k in calls[0].keywords if k.arg == "workers")
    assert workers == 1
    # Real Uvicorn configuration, including its environment fallback. No server starts.
    assert uvicorn.Config(object(), workers=workers).workers == 1
    assert uvicorn.Config("app.main:app").workers == 4
    assert "python /app/launch.py" in (ROOT / "Dockerfile").read_text()
