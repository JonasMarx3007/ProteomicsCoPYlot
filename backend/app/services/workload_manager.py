from __future__ import annotations

import asyncio
import os
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from threading import RLock
from typing import AsyncIterator, Deque

from app.services.session_context import get_session_id


_DEFAULT_QUEUE_TIMEOUT_SECONDS = 20.0


class HeavyWorkloadBusyError(RuntimeError):
    pass


def _positive_env_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = str(os.getenv(name, "")).strip()
    if not raw:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        return default


def _positive_env_float(name: str, default: float) -> float:
    raw = str(os.getenv(name, "")).strip()
    if not raw:
        return default
    try:
        return max(0.001, float(raw))
    except ValueError:
        return default


def heavy_max_concurrency() -> int:
    cpu_count = max(1, os.cpu_count() or 1)
    return _positive_env_int(
        "COPYLOT_HEAVY_MAX_CONCURRENCY",
        max(1, min(2, cpu_count)),
    )


def heavy_max_queue() -> int:
    return _positive_env_int(
        "COPYLOT_HEAVY_MAX_QUEUE",
        max(4, heavy_max_concurrency() * 4),
        minimum=0,
    )


def heavy_queue_timeout_seconds() -> float:
    return _positive_env_float(
        "COPYLOT_HEAVY_QUEUE_TIMEOUT_SECONDS",
        _DEFAULT_QUEUE_TIMEOUT_SECONDS,
    )


def sync_thread_worker_limit() -> int:
    default = max(16, heavy_max_concurrency() + 8)
    return _positive_env_int("COPYLOT_THREAD_WORKERS", default)


@dataclass
class _WorkloadGate:
    limit: int
    max_queue: int
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    active: int = 0
    waiting: int = 0
    active_by_session: dict[str, int] = field(default_factory=dict)
    waiting_by_session: dict[str, Deque[object]] = field(default_factory=dict)
    session_order: Deque[str] = field(default_factory=deque)

    def _activate(self, session_id: str) -> None:
        self.active += 1
        self.active_by_session[session_id] = self.active_by_session.get(session_id, 0) + 1

    def _deactivate(self, session_id: str) -> None:
        self.active -= 1
        remaining = self.active_by_session.get(session_id, 0) - 1
        if remaining > 0:
            self.active_by_session[session_id] = remaining
        else:
            self.active_by_session.pop(session_id, None)

    def _next_session(self) -> str | None:
        if not self.session_order:
            return None
        least_active = min(
            self.active_by_session.get(session_id, 0)
            for session_id in self.session_order
        )
        return next(
            session_id
            for session_id in self.session_order
            if self.active_by_session.get(session_id, 0) == least_active
        )

    def _can_start(self, session_id: str, token: object) -> bool:
        queue = self.waiting_by_session.get(session_id)
        return bool(
            self.active < self.limit
            and queue
            and queue[0] is token
            and self._next_session() == session_id
        )

    def _enqueue(self, session_id: str, token: object) -> None:
        queue = self.waiting_by_session.get(session_id)
        if queue is None:
            queue = deque()
            self.waiting_by_session[session_id] = queue
            self.session_order.append(session_id)
        queue.append(token)
        self.waiting += 1

    def _remove_waiter(self, session_id: str, token: object) -> bool:
        queue = self.waiting_by_session.get(session_id)
        if queue is None:
            return False
        try:
            queue.remove(token)
        except ValueError:
            return False
        self.waiting -= 1
        if not queue:
            self.waiting_by_session.pop(session_id, None)
            self.session_order.remove(session_id)
        return True

    def _grant(self, session_id: str, token: object) -> None:
        queue = self.waiting_by_session[session_id]
        if not queue or queue[0] is not token:
            raise RuntimeError("Heavy-work queue order changed while granting a slot.")
        queue.popleft()
        self.waiting -= 1
        self.session_order.remove(session_id)
        if queue:
            self.session_order.append(session_id)
        else:
            self.waiting_by_session.pop(session_id, None)
        self._activate(session_id)

    @asynccontextmanager
    async def slot(self, timeout_seconds: float, session_id: str) -> AsyncIterator[None]:
        acquired = False
        session_id = str(session_id or "global")
        async with self.condition:
            if self.active < self.limit and self.waiting == 0:
                self._activate(session_id)
                acquired = True
            else:
                if self.waiting >= self.max_queue:
                    raise HeavyWorkloadBusyError(
                        "The heavy-work queue is full. Try again after another analysis finishes."
                    )
                session_waiting = len(self.waiting_by_session.get(session_id, ()))
                # Preserve one queue position for another session whenever the
                # configured queue is large enough. This limits backlog, not
                # execution: an uncontended session can still use every worker.
                per_session_limit = self.max_queue
                if self.max_queue > 1:
                    per_session_limit -= 1
                if session_waiting >= per_session_limit:
                    raise HeavyWorkloadBusyError(
                        "This session already has several analyses waiting. "
                        "Let one finish before adding another."
                    )
                token = object()
                self._enqueue(session_id, token)
                try:
                    await asyncio.wait_for(
                        self.condition.wait_for(
                            lambda: self._can_start(session_id, token)
                        ),
                        timeout=timeout_seconds,
                    )
                    self._grant(session_id, token)
                    acquired = True
                except TimeoutError as exc:
                    raise HeavyWorkloadBusyError(
                        "The server remained busy while this analysis was waiting. Try again shortly."
                    ) from exc
                finally:
                    if self._remove_waiter(session_id, token):
                        self.condition.notify_all()
        try:
            yield
        finally:
            if acquired:
                async with self.condition:
                    self._deactivate(session_id)
                    self.condition.notify_all()


_GATES: dict[tuple[int, int, int], _WorkloadGate] = {}
_GATES_LOCK = RLock()


def _gate_for_current_loop(limit: int, max_queue: int) -> _WorkloadGate:
    key = (id(asyncio.get_running_loop()), limit, max_queue)
    with _GATES_LOCK:
        gate = _GATES.get(key)
        if gate is None:
            gate = _WorkloadGate(limit=limit, max_queue=max_queue)
            _GATES[key] = gate
        return gate


@asynccontextmanager
async def heavy_workload_scope(session_id: str | None = None) -> AsyncIterator[None]:
    gate = _gate_for_current_loop(heavy_max_concurrency(), heavy_max_queue())
    async with gate.slot(
        heavy_queue_timeout_seconds(),
        session_id or get_session_id(),
    ):
        yield


_HEAVY_PREFIXES = (
    "/api/analysis/",
    "/api/data-tools/",
    "/api/external/",
    "/api/plots/",
    "/api/qc/",
    "/api/stats/",
)
_HEAVY_EXACT = {
    "/api/annotations/generate",
    "/api/annotations/log2-detect",
    "/api/annotations/metadata/upload",
    "/api/annotations/phosprot/aggregate",
    "/api/annotations/phosprot/upload",
    "/api/datasets/upload",
    "/api/datasets/table-path",
    "/api/datasets/peptide-file",
    "/api/peptide/metadata/generate",
    "/api/peptide/metadata/upload",
    "/api/peptide/sequence-coverage",
    "/api/chat/module-context",
    "/api/restore/export",
    "/api/restore/import",
    "/api/summary/report",
    "/api/summary/tables",
}


def is_heavy_request(method: str, path: str) -> bool:
    if str(method).upper() == "OPTIONS":
        return False
    normalized = str(path or "").rstrip("/") or "/"
    return normalized in _HEAVY_EXACT or any(
        normalized.startswith(prefix) for prefix in _HEAVY_PREFIXES
    )
