"""M1 recovery and concurrency acceptance against disposable PostgreSQL 17."""

import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from app.core.exceptions import ConsultationError
from app.models.consultation import (
    Consultation,
    ConsultationMessage,
    ConsultationTurn,
    utcnow,
)
from app.services.consultation.llm import ConsultationLLM
from app.services.consultation.llm_fake import Fault
from app.services.consultation.runner import TurnRunner
from app.services.consultation.service import ConsultationService
from tests.consultation_helpers import make_environment, payload
from tests.test_org_postgres import migrate
from tests.test_org_postgres import pg_engine as pg_engine

# Re-run the same functional scenarios on PostgreSQL, in addition to its race tests.
from tests.test_consultation_service import (
    test_male_complete_flow_and_archive as test_male_complete_flow_and_archive,
    test_gate_supplement_is_saved_and_used_in_report as test_gate_supplement_is_saved_and_used_in_report,
    test_turn_identity_and_completed_replay as test_turn_identity_and_completed_replay,
    test_inputs_update_only_before_start as test_inputs_update_only_before_start,
)
from tests.test_consultation_recovery import (
    test_female_and_missing_sex_flows as test_female_and_missing_sex_flows,
    test_stale_version_returns_snapshot as test_stale_version_returns_snapshot,
    test_question_failure_falls_back_atomically as test_question_failure_falls_back_atomically,
    test_circuit_breaker_keeps_collecting_answers as test_circuit_breaker_keeps_collecting_answers,
    test_report_failure_retries_same_turn as test_report_failure_retries_same_turn,
    test_report_cannot_be_generated_twice as test_report_cannot_be_generated_twice,
    test_abandon_is_idempotent_and_allows_recreation as test_abandon_is_idempotent_and_allows_recreation,
    test_real_sse_disconnect_does_not_cancel_turn as test_real_sse_disconnect_does_not_cancel_turn,
)


@pytest.fixture
async def consultation_env(pg_engine):
    await migrate(pg_engine)
    env = make_environment(pg_engine)
    try:
        yield env
    finally:
        await env.runner.shutdown(timeout=0.5)


class GatedTransport:
    model_name = "gated-test"

    def __init__(self, partial=False):
        self.calls = []
        self.partial = partial
        self.started = [asyncio.Event(), asyncio.Event()]
        self.release = [asyncio.Event(), asyncio.Event()]

    async def stream(self, prompt, purpose, timeout, usage):
        index = len(self.calls)
        self.calls.append(prompt)
        self.started[index].set()
        if self.partial:
            yield "uncommitted partial text"
        await self.release[index].wait()
        yield f"attempt-{prompt.attempt}-call-{index}"


def gate(env, partial=False):
    transport = GatedTransport(partial)
    env.service.llm = ConsultationLLM(transport, env.sessions)
    return transport


def start_body():
    return {"turn_id": str(uuid4()), "kind": "start", "base_version": 0}


async def collect(env, handle):
    return [event async for event in env.service.events(handle)]


async def expire(env, handle):
    async with env.sessions() as db, db.begin():
        await db.execute(
            update(ConsultationTurn)
            .where(
                ConsultationTurn.org_id == handle.org_id,
                ConsultationTurn.consultation_id == handle.consultation_id,
                ConsultationTurn.turn_id == handle.turn_id,
            )
            .values(deadline_at=utcnow() - timedelta(seconds=1))
        )


async def test_concurrent_create_and_same_turn_are_idempotent(consultation_env):
    env = consultation_env
    body = payload()
    a, b = await asyncio.gather(
        *(env.service.create_or_get(env.ctx, body) for _ in range(2))
    )
    assert a["consultation_id"] == b["consultation_id"]
    transport = gate(env)
    turn = start_body()
    handles = await asyncio.gather(
        *(
            env.service.submit_turn(env.ctx, a["consultation_id"], turn)
            for _ in range(2)
        )
    )
    await asyncio.wait_for(transport.started[0].wait(), 2)
    transport.release[0].set()
    results = await asyncio.gather(*(collect(env, handle) for handle in handles))
    assert results[0][-1] == results[1][-1]
    assert len(transport.calls) == 1
    async with env.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Consultation)) == 1
        assert (
            await db.scalar(select(func.count()).select_from(ConsultationMessage)) == 1
        )


async def test_concurrent_different_turns_have_one_winner(consultation_env):
    env = consultation_env
    snapshot = await env.service.create_or_get(env.ctx, payload())
    transport = gate(env)
    results = await asyncio.gather(
        *(
            env.service.submit_turn(env.ctx, snapshot["consultation_id"], start_body())
            for _ in range(2)
        ),
        return_exceptions=True,
    )
    winners = [result for result in results if not isinstance(result, Exception)]
    errors = [result for result in results if isinstance(result, Exception)]
    assert len(winners) == len(errors) == 1
    assert isinstance(errors[0], ConsultationError)
    assert errors[0].code in {"SESSION_BUSY", "VERSION_CONFLICT"}
    transport.release[0].set()
    assert (await collect(env, winners[0]))[-1].name == "completed"


@pytest.mark.parametrize("partial", [False, True])
async def test_crashed_attempt_is_taken_over_after_deadline(consultation_env, partial):
    env = consultation_env
    snapshot = await env.service.create_or_get(env.ctx, payload())
    transport = gate(env, partial)
    body = start_body()
    handle = await env.service.submit_turn(env.ctx, snapshot["consultation_id"], body)
    await asyncio.wait_for(transport.started[0].wait(), 2)
    task = env.runner.task_by_key[(handle.consultation_id, handle.turn_id, 1)]
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert (
        await env.service.get_turn(env.ctx, handle.consultation_id, handle.turn_id)
    )["status"] == "processing"
    await expire(env, handle)
    pending = (await env.service.get_snapshot(env.ctx, handle.consultation_id))[
        "pending_turn"
    ]
    assert pending["status"] == "failed" and pending["retryable"]
    # Simulate a fresh worker with no knowledge of the old buffer or task.
    await env.runner.shutdown(0)
    env.runner = TurnRunner(retention=0.05)
    env.service = ConsultationService(env.sessions, llm=env.llm, task_runner=env.runner)
    resumed = await env.service.submit_turn(env.ctx, handle.consultation_id, body)
    assert resumed.attempt == 2
    events = await collect(env, resumed)
    assert events[1].name == "reset" and events[1].data["attempt"] == 2
    assert events[-1].name == "completed"
    snapshot = await env.service.get_snapshot(env.ctx, handle.consultation_id)
    assert snapshot["version"] == 1 and len(snapshot["messages"]) == 1


async def test_old_attempt_cannot_commit_after_takeover(consultation_env):
    env = consultation_env
    snapshot = await env.service.create_or_get(env.ctx, payload())
    transport = gate(env)
    body = start_body()
    old = await env.service.submit_turn(env.ctx, snapshot["consultation_id"], body)
    await asyncio.wait_for(transport.started[0].wait(), 2)
    old_task = env.runner.task_by_key[(old.consultation_id, old.turn_id, 1)]
    await expire(env, old)
    new = await env.service.submit_turn(env.ctx, old.consultation_id, body)
    await asyncio.wait_for(transport.started[1].wait(), 2)
    transport.release[0].set()
    await asyncio.wait_for(old_task, 2)
    unchanged = await env.service.get_snapshot(env.ctx, old.consultation_id)
    # Version is still zero: rejection must come from attempt fencing, not version alone.
    assert unchanged["version"] == 0 and unchanged["messages"] == []
    assert unchanged["pending_turn"]["attempt"] == 2
    transport.release[1].set()
    assert (await collect(env, new))[-1].name == "completed"
    saved = await env.service.get_snapshot(env.ctx, old.consultation_id)
    assert [m["content"] for m in saved["messages"]] == ["attempt-2-call-1"]


async def test_new_turn_replaces_expired_processing_turn(consultation_env):
    env = consultation_env
    snapshot = await env.service.create_or_get(env.ctx, payload())
    transport = gate(env)
    old_body = start_body()
    old = await env.service.submit_turn(env.ctx, snapshot["consultation_id"], old_body)
    await asyncio.wait_for(transport.started[0].wait(), 2)
    old_task = env.runner.task_by_key[(old.consultation_id, old.turn_id, 1)]
    await expire(env, old)
    new = await env.service.submit_turn(env.ctx, old.consultation_id, start_body())
    await asyncio.wait_for(transport.started[1].wait(), 2)
    assert (await env.service.get_turn(env.ctx, old.consultation_id, old.turn_id))[
        "status"
    ] == "failed"
    with pytest.raises(ConsultationError) as exc:
        await env.service.submit_turn(env.ctx, old.consultation_id, old_body)
    assert exc.value.code == "SESSION_BUSY"
    transport.release[0].set()
    await asyncio.wait_for(old_task, 2)
    transport.release[1].set()
    assert (await collect(env, new))[-1].name == "completed"
    saved = await env.service.get_snapshot(env.ctx, new.consultation_id)
    assert saved["version"] == 1 and len(saved["messages"]) == 1
    assert saved["messages"][0]["turn_id"] == new.turn_id


async def test_abandon_fences_inflight_result(consultation_env):
    env = consultation_env
    body = payload()
    snapshot = await env.service.create_or_get(env.ctx, body)
    transport = gate(env)
    handle = await env.service.submit_turn(
        env.ctx, snapshot["consultation_id"], start_body()
    )
    await asyncio.wait_for(transport.started[0].wait(), 2)
    task = env.runner.task_by_key[(handle.consultation_id, handle.turn_id, 1)]
    abandoned = await env.service.abandon(env.ctx, handle.consultation_id)
    assert abandoned["status"] == "abandoned"
    new = await env.service.create_or_get(env.ctx, body)
    assert new["consultation_id"] != handle.consultation_id
    transport.release[0].set()
    await asyncio.wait_for(task, 2)
    turn = await env.service.get_turn(env.ctx, handle.consultation_id, handle.turn_id)
    assert turn["status"] == "cancelled" and not turn["retryable"]
    assert (await env.service.get_snapshot(env.ctx, handle.consultation_id))[
        "messages"
    ] == []


async def test_other_worker_polls_for_committed_result(consultation_env):
    env = consultation_env
    snapshot = await env.service.create_or_get(env.ctx, payload())
    transport = gate(env)
    body = start_body()
    handle = await env.service.submit_turn(env.ctx, snapshot["consultation_id"], body)
    await asyncio.wait_for(transport.started[0].wait(), 2)
    other_runner = TurnRunner()
    other = ConsultationService(
        env.sessions, llm=env.llm, task_runner=other_runner, poll_interval=0.01
    )
    attached = await other.submit_turn(env.ctx, handle.consultation_id, body)

    async def read():
        return [event async for event in other.events(attached)]

    connection = asyncio.create_task(read())
    transport.release[0].set()
    try:
        events = await asyncio.wait_for(connection, 2)
        assert [e.name for e in events] == ["accepted", "completed"]
        assert len(transport.calls) == 1 and not other_runner.tasks
    finally:
        await other_runner.shutdown(0)


async def test_changed_inputs_during_start_require_retry(consultation_env):
    env = consultation_env
    body = payload()
    snapshot = await env.service.create_or_get(env.ctx, body)
    transport = gate(env)
    turn = start_body()
    handle = await env.service.submit_turn(env.ctx, snapshot["consultation_id"], turn)
    await asyncio.wait_for(transport.started[0].wait(), 2)
    body["inputs"]["patient"]["sex"] = "女"
    await env.service.create_or_get(env.ctx, body)
    transport.release[0].set()
    events = await collect(env, handle)
    assert events[-1].data == {"code": "INPUTS_CHANGED", "retryable": True}
    assert (await env.service.get_snapshot(env.ctx, handle.consultation_id))[
        "version"
    ] == 0
    retried = await env.service.submit_turn(env.ctx, handle.consultation_id, turn)
    await asyncio.wait_for(transport.started[1].wait(), 2)
    assert "- 性别: 女" in transport.calls[1].user_text
    transport.release[1].set()
    assert (await collect(env, retried))[-1].name == "completed"


async def test_task_timeout_leaves_no_half_messages(consultation_env):
    env = consultation_env
    snapshot = await env.service.create_or_get(env.ctx, payload())
    env.service.limits.question_task = 0.05
    env.transport.faults.append(Fault(delay_before=0.2))
    handle = await env.service.submit_turn(
        env.ctx, snapshot["consultation_id"], start_body()
    )
    events = await collect(env, handle)
    assert events[-1].name == "error" and events[-1].data["retryable"]
    snapshot = await env.service.get_snapshot(env.ctx, handle.consultation_id)
    assert snapshot["version"] == 0 and snapshot["messages"] == []
    assert snapshot["pending_turn"]["status"] == "failed"
