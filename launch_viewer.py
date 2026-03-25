from __future__ import annotations

import sys

from launch import main


def _ensure_arg(flag: str, value: str | None = None) -> None:
    if flag in sys.argv:
        return
    sys.argv.append(flag)
    if value is not None:
        sys.argv.append(value)


if __name__ == "__main__":
    _ensure_arg("--viewer")
    _ensure_arg("--port", "8001")
    main()
