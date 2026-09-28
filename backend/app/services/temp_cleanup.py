from __future__ import annotations

import os
from app.services.managed_temp import managed_temp_root
import time

_DEFAULT_MAX_AGE_SECONDS = 7 * 24 * 60 * 60


def cleanup_managed_temp_files() -> int:
    raw = str(os.getenv("COPYLOT_TEMP_FILE_MAX_AGE_SECONDS", "")).strip()
    try:
        max_age_seconds = max(1, int(raw)) if raw else _DEFAULT_MAX_AGE_SECONDS
    except ValueError:
        max_age_seconds = _DEFAULT_MAX_AGE_SECONDS

    root = managed_temp_root().resolve()
    if not root.is_dir():
        return 0

    cutoff = time.time() - max_age_seconds
    removed = 0
    for directory_name in ("table_uploads", "table_derived", "peptide_uploads", "restore_uploads"):
        directory = (root / directory_name).resolve()
        if root not in directory.parents or not directory.is_dir():
            continue
        for path in directory.rglob("*"):
            if not path.is_file():
                continue
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except OSError:
                continue
    return removed
