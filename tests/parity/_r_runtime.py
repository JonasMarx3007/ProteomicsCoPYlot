"""The Rscript the parity tests drive, found the way the app finds it.

Imported by the parity modules (`from _r_runtime import RSCRIPT`) instead of
each carrying its own copy. None when R is not installed; tests that need it
are marked `requires_r` and skip or fail through tests/conftest.py.
"""
from __future__ import annotations


def rscript() -> str | None:
    try:
        from app.services.r_runtime import detect_r_runtime
    except Exception:
        return None
    runtime = detect_r_runtime()
    return str(runtime["executable"]) if runtime.get("available") else None


RSCRIPT = rscript()
