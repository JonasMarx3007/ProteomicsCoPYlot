"""No source file starts with a UTF-8 byte-order mark.

Two files carried one (added by a Windows editor); it shows as garbage in
diffs and some tools, and strict linters reject it. Stripped once, and
guarded here so an editor set to "UTF-8 with BOM" cannot bring it back.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUFFIXES = {".py", ".ts", ".tsx", ".mjs", ".R", ".json", ".md", ".yml", ".yaml", ".toml", ".cfg"}
SKIP = {"node_modules", ".git", "dist", "build", "__pycache__", ".venv", "test-results"}


def test_no_source_file_starts_with_a_bom():
    offenders = []
    for path in ROOT.rglob("*"):
        if path.suffix not in SUFFIXES or not path.is_file():
            continue
        if any(part in SKIP for part in path.parts):
            continue
        with path.open("rb") as handle:
            if handle.read(3) == b"\xef\xbb\xbf":
                offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, offenders
