from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import pytest
from fastapi.testclient import TestClient
from starlette.concurrency import run_in_threadpool


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services import workload_manager
from app import main as main_module
from app.services.session_context import (
    get_session_id,
    reset_session_id,
    set_session_id,
)


@pytest.mark.parametrize(
    "method,path,expected",
    [
        ("GET", "/api/plots/qc/protein/pca.png", True),
        ("POST", "/api/stats/volcano", True),
        ("POST", "/api/restore/import", True),
        ("POST", "/api/annotations/generate", True),
        ("GET", "/api/health", False),
        ("GET", "/api/datasets/current", False),
        ("OPTIONS", "/api/plots/qc/protein/pca.png", False),
    ],
)
def test_heavy_request_classification(method: str, path: str, expected: bool) -> None:
    assert workload_manager.is_heavy_request(method, path) is expected


def test_gate_bounds_active_work_and_waiting_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COPYLOT_HEAVY_MAX_CONCURRENCY", "1")
    monkeypatch.setenv("COPYLOT_HEAVY_MAX_QUEUE", "1")
    monkeypatch.setenv("COPYLOT_HEAVY_QUEUE_TIMEOUT_SECONDS", "1")

    async def scenario() -> None:
        first_entered = asyncio.Event()
        release_first = asyncio.Event()
        second_entered = asyncio.Event()

        async def first() -> None:
            async with workload_manager.heavy_workload_scope():
                first_entered.set()
                await release_first.wait()

        async def second() -> None:
            await first_entered.wait()
            async with workload_manager.heavy_workload_scope():
                second_entered.set()

        first_task = asyncio.create_task(first())
        await first_entered.wait()
        second_task = asyncio.create_task(second())
        await asyncio.sleep(0.01)
        assert not second_entered.is_set()

        with pytest.raises(workload_manager.HeavyWorkloadBusyError, match="queue is full"):
            async with workload_manager.heavy_workload_scope():
                pass

        release_first.set()
        await asyncio.gather(first_task, second_task)
        assert second_entered.is_set()

    asyncio.run(scenario())


def test_waiting_work_times_out_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COPYLOT_HEAVY_MAX_CONCURRENCY", "1")
    monkeypatch.setenv("COPYLOT_HEAVY_MAX_QUEUE", "1")
    monkeypatch.setenv("COPYLOT_HEAVY_QUEUE_TIMEOUT_SECONDS", "0.01")

    async def scenario() -> None:
        async with workload_manager.heavy_workload_scope():
            with pytest.raises(workload_manager.HeavyWorkloadBusyError, match="remained busy"):
                async with workload_manager.heavy_workload_scope():
                    pass

    asyncio.run(scenario())


def test_one_session_can_use_every_available_worker() -> None:
    async def scenario() -> None:
        gate = workload_manager._WorkloadGate(limit=3, max_queue=6)
        all_entered = asyncio.Event()
        release = asyncio.Event()
        entered = 0

        async def work() -> None:
            nonlocal entered
            async with gate.slot(1.0, "session-a"):
                entered += 1
                if entered == 3:
                    all_entered.set()
                await release.wait()

        tasks = [asyncio.create_task(work()) for _ in range(3)]
        await asyncio.wait_for(all_entered.wait(), timeout=1.0)
        assert gate.active == 3
        assert gate.active_by_session == {"session-a": 3}
        release.set()
        await asyncio.gather(*tasks)

    asyncio.run(scenario())


def test_waiting_session_gets_next_slot_under_contention() -> None:
    async def scenario() -> None:
        gate = workload_manager._WorkloadGate(limit=2, max_queue=6)
        initial_entered = asyncio.Event()
        release_initial = [asyncio.Event(), asyncio.Event()]
        release_queued = asyncio.Event()
        active_initial = 0
        start_order: list[str] = []

        async def initial(index: int) -> None:
            nonlocal active_initial
            async with gate.slot(1.0, "session-a"):
                active_initial += 1
                if active_initial == 2:
                    initial_entered.set()
                await release_initial[index].wait()

        async def queued(session_id: str) -> None:
            async with gate.slot(1.0, session_id):
                start_order.append(session_id)
                await release_queued.wait()

        initial_tasks = [asyncio.create_task(initial(index)) for index in range(2)]
        await asyncio.wait_for(initial_entered.wait(), timeout=1.0)
        queued_a = asyncio.create_task(queued("session-a"))
        await asyncio.sleep(0.01)
        queued_b = asyncio.create_task(queued("session-b"))
        await asyncio.sleep(0.01)

        release_initial[0].set()
        for _ in range(100):
            if start_order:
                break
            await asyncio.sleep(0.01)
        assert start_order == ["session-b"]

        release_initial[1].set()
        for _ in range(100):
            if len(start_order) == 2:
                break
            await asyncio.sleep(0.01)

        assert start_order == ["session-b", "session-a"]
        release_queued.set()
        await asyncio.gather(*initial_tasks, queued_a, queued_b)

    asyncio.run(scenario())


def test_one_session_cannot_consume_the_entire_waiting_queue() -> None:
    async def scenario() -> None:
        gate = workload_manager._WorkloadGate(limit=1, max_queue=3)

        async def wait_for_slot(session_id: str) -> None:
            async with gate.slot(10.0, session_id):
                pass

        async with gate.slot(1.0, "session-a"):
            waiting = [
                asyncio.create_task(wait_for_slot("session-a"))
                for _ in range(2)
            ]
            for _ in range(100):
                if gate.waiting == 2:
                    break
                await asyncio.sleep(0.01)
            assert gate.waiting == 2

            with pytest.raises(
                workload_manager.HeavyWorkloadBusyError,
                match="already has several analyses waiting",
            ):
                async with gate.slot(1.0, "session-a"):
                    pass

            other_session = asyncio.create_task(wait_for_slot("session-b"))
            for _ in range(100):
                if gate.waiting == 3:
                    break
                await asyncio.sleep(0.01)
            assert gate.waiting == 3

            for task in [*waiting, other_session]:
                task.cancel()
            await asyncio.gather(*waiting, other_session, return_exceptions=True)
            assert gate.waiting == 0

    asyncio.run(scenario())


def test_invalid_environment_values_fall_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COPYLOT_HEAVY_MAX_CONCURRENCY", "invalid")
    monkeypatch.setenv("COPYLOT_HEAVY_MAX_QUEUE", "invalid")
    monkeypatch.setenv("COPYLOT_HEAVY_QUEUE_TIMEOUT_SECONDS", "invalid")
    monkeypatch.setenv("COPYLOT_THREAD_WORKERS", "invalid")
    assert workload_manager.heavy_max_concurrency() >= 1
    assert workload_manager.heavy_max_queue() >= 0
    assert workload_manager.heavy_queue_timeout_seconds() > 0
    assert workload_manager.sync_thread_worker_limit() >= 1


def test_busy_heavy_request_returns_retryable_503_without_blocking_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @asynccontextmanager
    async def always_busy(_session_id: str | None = None) -> AsyncIterator[None]:
        raise workload_manager.HeavyWorkloadBusyError("test queue full")
        yield

    monkeypatch.setattr(main_module, "heavy_workload_scope", always_busy)
    with TestClient(main_module.app) as client:
        busy = client.get("/api/plots/test-heavy-path")
        assert busy.status_code == 503
        assert busy.json() == {"detail": "test queue full"}
        assert busy.headers["Retry-After"] == "2"
        assert busy.headers["X-Content-Type-Options"] == "nosniff"

        health = client.get("/api/health")
        assert health.status_code == 200


def test_worker_dispatch_preserves_session_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COPYLOT_SESSION_ISOLATION", "1")

    async def scenario() -> None:
        token = set_session_id("session_worker_context")
        try:
            assert await run_in_threadpool(get_session_id) == "session_worker_context"
        finally:
            reset_session_id(token)

    asyncio.run(scenario())
