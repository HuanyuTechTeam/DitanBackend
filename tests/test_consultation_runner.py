import asyncio

from app.services.consultation.runner import TurnRunner


async def test_runner_replays_and_releases_finished_buffers():
    runner = TurnRunner(retention=0.01)
    release = asyncio.Event()
    key = ("consultation", "turn", 1)

    async def execute(buffer):
        await buffer.publish("delta", {"attempt": 1, "offset": 0, "text": "内容"})
        await release.wait()
        await buffer.publish("completed", {"turn_id": "turn"})

    buffer = runner.start(key, execute)
    subscription = buffer.subscribe(heartbeat=0.01)
    assert (await anext(subscription)).name == "delta"
    assert (await anext(subscription)).name == "heartbeat"
    await subscription.aclose()
    assert runner.tasks
    release.set()
    events = [event async for event in buffer.subscribe()]
    assert [event.name for event in events] == ["delta", "completed"]
    await asyncio.sleep(0.03)
    assert not runner.entries and not runner.tasks and not runner.cleanup_handles
    await runner.shutdown(0)


async def test_shutdown_has_a_total_deadline_even_if_task_resists_cancellation():
    runner = TurnRunner()
    release = asyncio.Event()
    started = asyncio.Event()

    async def execute(buffer):
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()
        await buffer.publish("completed", {})

    runner.start(("c", "t", 1), execute)
    await started.wait()
    task = next(iter(runner.tasks))
    before = asyncio.get_running_loop().time()
    await runner.shutdown(timeout=0.03)
    assert asyncio.get_running_loop().time() - before < 0.2
    assert not task.done()
    release.set()
    await task


async def test_shutdown_waits_for_a_finishing_turn():
    runner = TurnRunner()

    async def execute(buffer):
        await asyncio.sleep(0.01)
        await buffer.publish("completed", {"turn_id": "t"})

    buffer = runner.start(("c", "t", 1), execute)
    await runner.shutdown(timeout=0.2)
    assert buffer.events[-1].name == "completed" and not runner.tasks
