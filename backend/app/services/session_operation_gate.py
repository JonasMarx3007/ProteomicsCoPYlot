from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from threading import RLock
from typing import AsyncIterator


@dataclass
class _SessionGate:
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    readers: int = 0
    writer: bool = False
    waiting_writers: int = 0
    # Requests holding or waiting for this gate; guarded by _GATES_LOCK. The gate
    # is dropped when it reaches zero, so sessions do not leave gates behind.
    users: int = 0

    @asynccontextmanager
    async def shared(self) -> AsyncIterator[None]:
        async with self.condition:
            await self.condition.wait_for(
                lambda: not self.writer and self.waiting_writers == 0
            )
            self.readers += 1
        try:
            yield
        finally:
            async with self.condition:
                self.readers -= 1
                if self.readers == 0:
                    self.condition.notify_all()

    @asynccontextmanager
    async def exclusive(self) -> AsyncIterator[None]:
        async with self.condition:
            self.waiting_writers += 1
            try:
                await self.condition.wait_for(
                    lambda: not self.writer and self.readers == 0
                )
                self.writer = True
            finally:
                self.waiting_writers -= 1
        try:
            yield
        finally:
            async with self.condition:
                self.writer = False
                self.condition.notify_all()


_GATES: dict[tuple[int, str], _SessionGate] = {}
_GATES_LOCK = RLock()


def _acquire_gate(key: tuple[int, str]) -> _SessionGate:
    with _GATES_LOCK:
        gate = _GATES.get(key)
        if gate is None:
            gate = _SessionGate()
            _GATES[key] = gate
        gate.users += 1
        return gate


def _release_gate(key: tuple[int, str], gate: _SessionGate) -> None:
    with _GATES_LOCK:
        gate.users -= 1
        if gate.users <= 0 and _GATES.get(key) is gate:
            del _GATES[key]


def active_gate_count() -> int:
    """How many session gates exist; for tests and diagnostics."""
    with _GATES_LOCK:
        return len(_GATES)


@asynccontextmanager
async def session_operation_scope(
    session_id: str,
    *,
    exclusive: bool = False,
) -> AsyncIterator[None]:
    """Run changes to a session's data one at a time; reads overlap freely.

    A request that changes the session's datasets or annotations takes the gate
    exclusively, so two of them cannot interleave and no read sees a half-made
    change. The gate exists only while a request of the session uses it.
    """
    key = (id(asyncio.get_running_loop()), session_id)
    gate = _acquire_gate(key)
    try:
        manager = gate.exclusive() if exclusive else gate.shared()
        async with manager:
            yield
    finally:
        _release_gate(key, gate)
