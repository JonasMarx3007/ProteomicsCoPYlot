from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Literal

RDetectionSource = Literal["env", "path", "common_path"]


def _dedupe(values: list[tuple[Path, RDetectionSource]]) -> list[tuple[Path, RDetectionSource]]:
    seen: set[str] = set()
    output: list[tuple[Path, RDetectionSource]] = []
    for path, source in values:
        key = str(path).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        output.append((path, source))
    return output


def _common_rscript_paths() -> list[Path]:
    system = platform.system().lower()
    candidates: list[Path] = []

    if system == "windows":
        roots = [
            os.getenv("ProgramFiles", ""),
            os.getenv("ProgramFiles(x86)", ""),
            os.getenv("LOCALAPPDATA", ""),
        ]
        for root in [Path(value) for value in roots if value]:
            r_root = root / "R"
            if not r_root.is_dir():
                continue
            candidates.extend(sorted(r_root.glob("R-*/bin/Rscript.exe"), reverse=True))
            candidates.extend(sorted(r_root.glob("R-*/bin/x64/Rscript.exe"), reverse=True))
    elif system == "darwin":
        candidates.extend(
            [
                Path("/opt/homebrew/bin/Rscript"),
                Path("/usr/local/bin/Rscript"),
                Path("/Library/Frameworks/R.framework/Resources/bin/Rscript"),
                Path("/usr/bin/Rscript"),
            ]
        )
    else:
        candidates.extend(
            [
                Path("/usr/local/bin/Rscript"),
                Path("/usr/bin/Rscript"),
                Path("/bin/Rscript"),
            ]
        )

    return candidates


def _candidate_paths() -> list[tuple[Path, RDetectionSource]]:
    candidates: list[tuple[Path, RDetectionSource]] = []

    for env_name in ("COPYLOT_RSCRIPT", "COPYLOT_R_BINARY", "RSCRIPT"):
        value = os.getenv(env_name, "").strip()
        if value:
            candidates.append((Path(value), "env"))

    for executable in ("Rscript", "Rscript.exe"):
        found = shutil.which(executable)
        if found:
            candidates.append((Path(found), "path"))

    candidates.extend((path, "common_path") for path in _common_rscript_paths())
    return _dedupe(candidates)


def _parse_r_version(output: str) -> str | None:
    match = re.search(r"version\s+([0-9]+(?:\.[0-9]+)+)", output, flags=re.IGNORECASE)
    if match:
        return match.group(1)
    return None


def _run_version_probe(path: Path) -> tuple[bool, str | None, str | None]:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            [str(path), "--version"],
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
            creationflags=creationflags,
        )
    except Exception as exc:
        return False, None, str(exc)

    output = "\n".join(
        part.strip()
        for part in (completed.stdout, completed.stderr)
        if part and part.strip()
    )
    if completed.returncode != 0:
        return False, output or None, f"Rscript exited with code {completed.returncode}"
    return True, output or None, None


@lru_cache(maxsize=1)
def detect_r_runtime() -> dict[str, object]:
    errors: list[str] = []
    candidates = _candidate_paths()

    for path, source in candidates:
        if path.is_absolute() and not path.is_file():
            errors.append(f"{path}: not found")
            continue

        ok, output, error = _run_version_probe(path)
        if ok:
            return {
                "available": True,
                "executable": str(path),
                "version": _parse_r_version(output or ""),
                "versionOutput": output,
                "detectedFrom": source,
                "candidates": [str(candidate) for candidate, _ in candidates],
                "error": None,
            }
        errors.append(f"{path}: {error or output or 'unusable'}")

    return {
        "available": False,
        "executable": None,
        "version": None,
        "versionOutput": None,
        "detectedFrom": None,
        "candidates": [str(candidate) for candidate, _ in candidates],
        "error": "; ".join(errors) if errors else "Rscript was not found.",
    }


def clear_r_runtime_cache() -> None:
    detect_r_runtime.cache_clear()
