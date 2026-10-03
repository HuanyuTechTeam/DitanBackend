"""Detached tasks and ephemeral replay buffers; correctness lives in the database."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)
Key = tuple[str, str, int]


@dataclass(frozen=True)
class Event:
    name: str
    data: dict


@dataclass
class Buffer:
    events: list[Event] = field(default_factory=list)
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    finished: bool = False

    async def publish(self, name: str, data: dict):
        async with self.condition:
            if self.finished:
                return
            self.events.append(Event(name, data))
            self.finished = name in {"completed", "error"}
            self.condition.notify_all()

    async def subscribe(self, heartbeat: float = 15) -> AsyncIterator[Event]:
        index = 0
        while True:
            heartbeat_due = False
            async with self.condition:
                if index == len(self.events) and not self.finished:
                    try:
                        await asyncio.wait_for(self.condition.wait(), heartbeat)
                    except TimeoutError:
                        heartbeat_due = True
                available = self.events[index:]
                index = len(self.events)
                finished = self.finished
            for event in available:
                yield event
            if finished:
                return
            if heartbeat_due:
                yield Event("heartbeat", {})


class TurnRunner:
    def __init__(self, retention: float = 60):
        self.entries: dict[Key, Buffer] = {}
        self.tasks: set[asyncio.Task] = set()
        self.task_by_key: dict[Key, asyncio.Task] = {}
        self.cleanup_handles: dict[Key, asyncio.TimerHandle] = {}
        self.retention = retention
        self.closing = False

    def start(self, key: Key, execute: Callable[[Buffer], Awaitable[None]]) -> Buffer:
        if key in self.entries:
            return self.entries[key]
        if self.closing:
            raise RuntimeError("Consultation runner is shutting down")
        buffer = self.entries[key] = Buffer()

        async def run():
            try:
                await execute(buffer)
            except asyncio.CancelledError:
                await buffer.publish(
                    "error", {"code": "TURN_INTERRUPTED", "retryable": True}
                )
                raise
            except Exception:
                logger.error(
                    "Consultation task failed",
                    extra={
                        "consultation_id": key[0],
                        "turn_id": key[1],
                        "attempt": key[2],
                    },
                )
            finally:
                if not buffer.finished:
                    await buffer.publish(
                        "error", {"code": "MODEL_UNAVAILABLE", "retryable": True}
                    )

        task = asyncio.create_task(
            run(), name=f"consultation:{key[0]}:{key[1]}:{key[2]}"
        )
        self.tasks.add(task)
        self.task_by_key[key] = task

        def done(completed):
            self.tasks.discard(completed)
            self.task_by_key.pop(key, None)
            if not self.closing:
                self.cleanup_handles[key] = asyncio.get_running_loop().call_later(
                    self.retention, self._clean, key
                )

        task.add_done_callback(done)
        return buffer

    def _clean(self, key: Key):
        self.entries.pop(key, None)
        self.cleanup_handles.pop(key, None)

    async def shutdown(self, timeout: float = 60):
        self.closing = True
        if self.tasks:
            _, pending = await asyncio.wait(list(self.tasks), timeout=timeout)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        for handle in self.cleanup_handles.values():
            handle.cancel()
        self.cleanup_handles.clear()
        self.entries.clear()


runner = TurnRunner()
