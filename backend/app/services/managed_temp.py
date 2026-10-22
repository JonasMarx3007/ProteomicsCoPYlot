"""The tool's own directories under the system temp folder.

Uploaded tables, peptide reports and restore replacements are released when
no dataset needs them. Startup cleanup removes old crash leftovers. On a shared machine the system temp folder is readable
by every account, and files created with the default mode (0644) are too, so
everything here is created private: directories 0700, files 0600. Windows
ignores POSIX modes; there the per-user temp folder is already private.
"""

from __future__ import annotations

import os
import stat
import sys
import tempfile
from pathlib import Path

_PRIVATE_DIR = stat.S_IRWXU
_PRIVATE_FILE = stat.S_IRUSR | stat.S_IWUSR


def managed_temp_root() -> Path:
    return Path(tempfile.gettempdir()) / "ProteomicsCoPYlot"


def private_temp_dir(name: str) -> Path:
    """`<temp>/ProteomicsCoPYlot/<name>`, created for the current user only."""
    root = managed_temp_root()
    directory = root / name
    if not name or Path(name).name != name or name in {".", ".."}:
        raise ValueError("A managed temporary directory must have a single directory name.")
    for path in (root, directory):
        path.mkdir(exist_ok=True, mode=_PRIVATE_DIR)
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise OSError("A managed temporary directory must not be a symbolic link.")
        if sys.platform != "win32":
            if info.st_uid != os.getuid():
                raise PermissionError("A managed temporary directory belongs to another user.")
            if stat.S_IMODE(info.st_mode) != _PRIVATE_DIR:
                path.chmod(_PRIVATE_DIR)
    return directory


def open_private(path: Path, mode: str = "wb"):
    """Open `path` for writing with permissions for the current user only."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if os.name == "nt":
        flags |= getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(path, flags | os.O_EXCL, _PRIVATE_FILE)
    except FileExistsError:
        descriptor = os.open(path, flags, _PRIVATE_FILE)
    else:
        from app.services.temp_file_lifecycle import register_created_file

        try:
            register_created_file(path, os.fstat(descriptor))
        except BaseException:
            os.close(descriptor)
            raise
    if "b" in mode:
        return os.fdopen(descriptor, mode)
    return os.fdopen(descriptor, mode, encoding="utf-8", newline="")


def write_private_bytes(path: Path, content: bytes) -> None:
    with open_private(path, "wb") as handle:
        handle.write(content)
