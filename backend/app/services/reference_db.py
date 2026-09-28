"""Where the bundled reference data lives, whatever shape the install has."""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

LOGGER = logging.getLogger(__name__)


def reference_db_candidates(filename: str) -> list[Path]:
    """``data/db/<filename>`` under every root this application can run from.

    A checkout, a PyInstaller bundle (``sys._MEIPASS``, or the folder beside the
    executable), a pip install (``sys.prefix``), the per-user copy under
    LOCALAPPDATA, and a sibling checkout.

    Three modules each carried their own copy of this list and they had drifted:
    the identifier database was not looked for under ``sys.prefix`` and the FASTA
    files were looked for in the checkout only, so a frozen or pip-installed
    build could find the Gene Ontology table and neither of the other two.
    """
    project_root = Path(__file__).resolve().parents[3]
    roots: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
    roots.append(Path(sys.prefix))
    local_appdata = os.getenv("LOCALAPPDATA", "").strip()
    if local_appdata:
        roots.append(Path(local_appdata) / "proteomics-copylot")
    roots.extend([project_root, project_root.parent / "proteomics-copylot"])

    candidates: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        candidate = root / "data" / "db" / filename
        if str(candidate) not in seen:
            seen.add(str(candidate))
            candidates.append(candidate)
    return candidates


def resolve_reference_db(filename: str, description: str) -> Path:
    """The first candidate that exists.

    The searched paths carry the user's account name, so they go to the log and
    never into the response (``tests/backend/test_error_disclosure.py``).
    """
    candidates = reference_db_candidates(filename)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    LOGGER.error("%s not found. Searched: %s", filename, ", ".join(str(path) for path in candidates))
    raise ValueError(
        f"Could not find the bundled {description}. "
        "The searched locations are recorded in the server log."
    )
