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


async def _gate_for(session_id: str) -> _SessionGate:
    key = (id(asyncio.get_running_loop()), session_id)
    with _GATES_LOCK:
        gate = _GATES.get(key)
        if gate is None:
            gate = _SessionGate()
            _GATES[key] = gate
        return gate


@asynccontextmanager
async def session_operation_scope(
    session_id: str,
    *,
    exclusive: bool = False,
) -> AsyncIterator[None]:
    """Keep restore/reset exclusive while allowing ordinary session reads to overlap."""
    gate = await _gate_for(session_id)
    manager = gate.exclusive() if exclusive else gate.shared()
    async with manager:
        yield
