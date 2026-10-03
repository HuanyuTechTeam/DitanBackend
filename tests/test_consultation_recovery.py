import asyncio
import json
from uuid import uuid4

import pytest

from app.api.deps import get_consultation_context
from app.core.exceptions import ConsultationError
from app.models.consultation import utcnow
from app.services.consultation.llm_fake import Fault
from app.services.consultation.rendering import BEIJING
from app.services.consultation.service import get_service
from main import app
from tests.consultation_helpers import payload, ready, send
from tests.consultation_helpers import consultation_env as consultation_env


@pytest.mark.parametrize(
    "sex,age,extra",
    [
        ("女", 25, ["children", "menstruation", "menstruation_detail", "leukorrhea"]),
        ("女", 15, ["menstruation", "menstruation_detail", "leukorrhea"]),
        ("女", 8, []),
        (None, 25, []),
    ],
)
async def test_female_and_missing_sex_flows(consultation_env, sex, age, extra):
    env = consultation_env
    year = utcnow().astimezone(BEIJING).year - age
    snapshot = await ready(env, payload(sex, f"{year}-01-01"))
    questions = [m["step_id"] for m in snapshot["messages"] if m["role"] == "assistant"]
    assert questions == [
        "core_history",
        "family_health",
        "work_stress",
        "sleep_quality",
        "nocturia",
        "energy_mood",
        "diet_core",
        "diet_extra",
        "digestion",
        "exercise_habit",
        "exercise_tolerance",
        *extra,
        "report_gate",
    ]


async def test_stale_version_returns_snapshot(consultation_env):
    env = consultation_env
    snapshot = await env.service.create_or_get(env.ctx, payload())
    snapshot, _, _ = await send(env, snapshot, "start")
    with pytest.raises(ConsultationError) as exc:
        await env.service.submit_turn(
            env.ctx,
            snapshot["consultation_id"],
            {
                "turn_id": str(uuid4()),
                "kind": "answer",
                "base_version": 0,
                "text": "旧回答",
            },
        )
    assert exc.value.code == "VERSION_CONFLICT"
    assert exc.value.data["snapshot"] == snapshot


@pytest.mark.parametrize("fail_after", [0, 1])
async def test_question_failure_falls_back_atomically(consultation_env, fail_after):
    env = consultation_env
    env.transport.faults.append(Fault(fail_after=fail_after))
    snapshot = await env.service.create_or_get(env.ctx, payload())
    snapshot, events, _ = await send(env, snapshot, "start")
    message = snapshot["messages"][0]
    assert message["meta"]["fallback"] is True
    assert (
        message["content"]
        == "有没有高血压、糖尿病、脂肪肝、甲状腺这类问题？或者其他需要长期吃药的疾病？"
    )
    names = [e.name for e in events]
    assert ("reset" in names) == bool(fail_after)
    final_delta = next(e.data for e in reversed(events) if e.name == "delta")
    assert final_delta["text"] == message["content"] and final_delta["offset"] == 0
    if fail_after:
        assert names.index("reset") < len(names) - 2


async def test_circuit_breaker_keeps_collecting_answers(consultation_env):
    env = consultation_env
    env.transport.faults.extend(Fault(fail_after=0) for _ in range(3))
    snapshot = await env.service.create_or_get(env.ctx, payload())
    snapshot, _, _ = await send(env, snapshot, "start")
    while snapshot["status"] == "collecting":
        snapshot, _, _ = await send(env, snapshot)
    assert len(env.transport.calls) == 3
    assert snapshot["version"] == 12 and snapshot["can_report"]
    assert all(
        m["meta"]["fallback"]
        for m in snapshot["messages"]
        if m["role"] == "assistant" and m["step_id"] != "report_gate"
    )
    assert len([m for m in snapshot["messages"] if m["role"] == "user"]) == 11


async def test_report_failure_retries_same_turn(consultation_env):
    env = consultation_env
    snapshot = await ready(env)
    env.transport.faults.extend([Fault(fail_after=0), Fault(fail_after=0)])
    body = {
        "turn_id": str(uuid4()),
        "kind": "report",
        "base_version": snapshot["version"],
    }
    handle = await env.service.submit_turn(env.ctx, snapshot["consultation_id"], body)
    failed = [event async for event in env.service.events(handle)]
    assert failed[-1].data == {"code": "MODEL_UNAVAILABLE", "retryable": True}
    pending = await env.service.get_snapshot(env.ctx, snapshot["consultation_id"])
    assert pending["status"] == "ready_for_report"
    assert pending["messages"] == snapshot["messages"]
    assert pending["pending_turn"]["status"] == "failed"
    handle = await env.service.submit_turn(env.ctx, snapshot["consultation_id"], body)
    assert handle.attempt == 2
    events = [event async for event in env.service.events(handle)]
    protocol_events = [event for event in events if event.name != "heartbeat"]
    assert (
        protocol_events[1].name == "reset" and protocol_events[1].data["attempt"] == 2
    )
    assert events[-1].name == "completed"
    complete = await env.service.get_snapshot(env.ctx, snapshot["consultation_id"])
    assert complete["version"] == snapshot["version"] + 1
    assert len(complete["messages"]) == len(snapshot["messages"]) + 1


async def test_report_cannot_be_generated_twice(consultation_env):
    env = consultation_env
    snapshot = await ready(env)
    snapshot, _, _ = await send(env, snapshot, "report")
    with pytest.raises(ConsultationError) as exc:
        await env.service.submit_turn(
            env.ctx,
            snapshot["consultation_id"],
            {
                "turn_id": str(uuid4()),
                "kind": "report",
                "base_version": snapshot["version"],
            },
        )
    assert exc.value.code in {"REPORT_NOT_READY", "CONSULTATION_CLOSED"}
    assert len([m for m in snapshot["messages"] if m["kind"] == "report"]) == 1


async def test_abandon_is_idempotent_and_allows_recreation(consultation_env):
    env = consultation_env
    body = payload()
    snapshot = await env.service.create_or_get(env.ctx, body)
    snapshot, _, _ = await send(env, snapshot, "start")
    abandoned = await env.service.abandon(env.ctx, snapshot["consultation_id"])
    assert abandoned["messages"] == snapshot["messages"]
    assert await env.service.abandon(env.ctx, snapshot["consultation_id"]) == abandoned
    new = await env.service.create_or_get(env.ctx, body)
    assert new["consultation_id"] != abandoned["consultation_id"]
    assert new["version"] == 0 and new["messages"] == []


async def test_real_sse_disconnect_does_not_cancel_turn(consultation_env, monkeypatch):
    env = consultation_env
    monkeypatch.setitem(app.dependency_overrides, get_service, lambda: env.service)
    monkeypatch.setitem(
        app.dependency_overrides, get_consultation_context, lambda: env.ctx
    )
    snapshot = await env.service.create_or_get(env.ctx, payload())
    env.transport.faults.append(Fault(delay_between=0.02, chunk_size=2))
    body = {"turn_id": str(uuid4()), "kind": "start", "base_version": 0}
    request_body = json.dumps(body).encode()
    incoming = asyncio.Queue()
    await incoming.put(
        {"type": "http.request", "body": request_body, "more_body": False}
    )
    received_delta = asyncio.Event()
    frames = []

    async def receive():
        return await incoming.get()

    async def send_frame(message):
        frames.append(message)
        if message["type"] == "http.response.body" and b"event: delta" in message.get(
            "body", b""
        ):
            received_delta.set()

    path = f"/api/v1/consultations/{snapshot['consultation_id']}/turns"
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(request_body)).encode()),
        ],
        "client": ("127.0.0.1", 1),
        "server": ("test", 80),
    }
    connection = asyncio.create_task(app(scope, receive, send_frame))
    try:
        await asyncio.wait_for(received_delta.wait(), 2)
        assert not any(
            b"event: completed" in frame.get("body", b"") for frame in frames
        )
        await incoming.put({"type": "http.disconnect"})
        await asyncio.wait_for(connection, 2)
        await asyncio.wait_for(asyncio.gather(*list(env.runner.tasks)), 3)
    finally:
        if not connection.done():
            connection.cancel()
            await asyncio.gather(connection, return_exceptions=True)
    turn = await env.service.get_turn(
        env.ctx, snapshot["consultation_id"], body["turn_id"]
    )
    assert turn["status"] == "completed"
    resumed = await env.service.submit_turn(env.ctx, snapshot["consultation_id"], body)
    events = [event async for event in env.service.events(resumed)]
    assert events[-1].data == turn["result"]
    assert len(env.transport.calls) == 1
