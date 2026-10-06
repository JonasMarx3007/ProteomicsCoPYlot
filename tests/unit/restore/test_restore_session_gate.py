from __future__ import annotations

import asyncio
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]

from app.services.session_operation_gate import session_operation_scope


def test_restore_scope_waits_for_reads_and_blocks_new_reads() -> None:
    async def scenario() -> None:
        first_reader_entered = asyncio.Event()
        release_first_reader = asyncio.Event()
        writer_entered = asyncio.Event()
        release_writer = asyncio.Event()
        second_reader_entered = asyncio.Event()

        async def first_reader() -> None:
            async with session_operation_scope("gate-test", exclusive=False):
                first_reader_entered.set()
                await release_first_reader.wait()

        async def writer() -> None:
            await first_reader_entered.wait()
            async with session_operation_scope("gate-test", exclusive=True):
                writer_entered.set()
                await release_writer.wait()

        async def second_reader() -> None:
            await first_reader_entered.wait()
            await asyncio.sleep(0)
            async with session_operation_scope("gate-test", exclusive=False):
                second_reader_entered.set()

        tasks = [
            asyncio.create_task(first_reader()),
            asyncio.create_task(writer()),
            asyncio.create_task(second_reader()),
        ]
        await first_reader_entered.wait()
        await asyncio.sleep(0.01)
        assert not writer_entered.is_set()
        assert not second_reader_entered.is_set()

        release_first_reader.set()
        await writer_entered.wait()
        assert not second_reader_entered.is_set()

        release_writer.set()
        await asyncio.gather(*tasks)
        assert second_reader_entered.is_set()

    asyncio.run(scenario())


def test_different_sessions_do_not_block_each_other() -> None:
    async def scenario() -> None:
        release_writer = asyncio.Event()
        writer_entered = asyncio.Event()
        other_reader_entered = asyncio.Event()

        async def writer() -> None:
            async with session_operation_scope("session-one", exclusive=True):
                writer_entered.set()
                await release_writer.wait()

        async def other_reader() -> None:
            await writer_entered.wait()
            async with session_operation_scope("session-two", exclusive=False):
                other_reader_entered.set()

        writer_task = asyncio.create_task(writer())
        reader_task = asyncio.create_task(other_reader())
        await other_reader_entered.wait()
        release_writer.set()
        await asyncio.gather(writer_task, reader_task)

    asyncio.run(scenario())
