"""Bound expensive password checks across all client addresses.

Admission is immediate: excess requests do not queue in the shared worker pool.
All admitted attempts spend the rolling budget, including successful logins.
The deployment runs one worker, so this process-wide budget is server-wide.

The viewer login scans every project hash, the tool login checks one: each has its own budget and environment variables
(`COPYLOT_VIEWER_PASSWORD_*`, `COPYLOT_TOOL_PASSWORD_*`), the same limits.
"""
from __future__ import annotations

import math
import time
from collections import deque
from contextlib import contextmanager
from threading import Lock
from typing import Iterator

from app.services.env_settings import env_int


class ViewerLoginCapacityError(RuntimeError):
    def __init__(self, retry_after: int, label: str = "Viewer"):
        super().__init__(f"{label} login is busy. Please wait and try again.")
        self.retry_after = retry_after


class ViewerPasswordBudget:
    """One rolling budget; `label` names the login ("Viewer", "Tool") in the
    429 message and picks the `COPYLOT_<LABEL>_PASSWORD_*` variables."""

    def __init__(self, label: str = "Viewer") -> None:
        self._lock = Lock()
        self._attempts: deque[float] = deque()
        self._active = 0
        self.label = label
        self._prefix = f"COPYLOT_{label.upper()}_PASSWORD_"

    @contextmanager
    def check(self) -> Iterator[None]:
        concurrency = env_int(self._prefix + "MAX_CONCURRENCY", 2, minimum=1)
        limit = env_int(self._prefix + "MAX_ATTEMPTS", 30, minimum=1)
        window = env_int(self._prefix + "WINDOW_SECONDS", 60, minimum=1)
        with self._lock:
            now = time.monotonic()
            while self._attempts and self._attempts[0] <= now - window:
                self._attempts.popleft()
            if len(self._attempts) >= limit:
                raise ViewerLoginCapacityError(max(1, math.ceil(self._attempts[0] + window - now)), self.label)
            if self._active >= concurrency:
                raise ViewerLoginCapacityError(1, self.label)
            self._attempts.append(now)
            self._active += 1
        try:
            yield
        finally:
            with self._lock:
                self._active -= 1
