import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("workflow", ["tests.yml", "cross-implementation.yml"])
@pytest.mark.parametrize("artifacts", [(), ("Rplots.pdf",), ("VennDiagram.probe.log",),
                                       ("Rplots.pdf", "VennDiagram.probe.log")])
def test_ci_rejects_any_root_artifact(tmp_path, workflow, artifacts):
    bash = shutil.which("bash")
    if os.name == "nt":
        git_bash = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe"
        if git_bash.is_file():
            bash = str(git_bash)
    assert bash, "Bash is required to verify the CI artifact guard"
    source = (ROOT / ".github/workflows" / workflow).read_text(encoding="utf-8")
    match = re.search(r"- name: Fail if the run littered the working tree\n        run: \|\n((?:          [^\n]*\n)+)", source)
    assert match, "Could not locate the artifact guard"
    script = "\n".join(line[10:] for line in match[1].splitlines())
    for name in artifacts:
        (tmp_path / name).write_text("synthetic artifact", encoding="utf-8")
    result = subprocess.run([bash, "--noprofile", "--norc", "-eo", "pipefail", "-c", script],
                            cwd=tmp_path, capture_output=True, text=True, timeout=10)
    assert result.returncode == (1 if artifacts else 0), result.stderr
    for name in artifacts:
        assert name in result.stdout
        assert (tmp_path / name).is_file(), "The guard must report, not delete, artifacts"
