from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.exceptions import ConsultationError
from app.models.consultation import Consultation
from tests.consultation_helpers import payload, ready, send
from tests.consultation_helpers import consultation_env as consultation_env


async def test_male_complete_flow_and_archive(consultation_env):
    env = consultation_env
    snapshot = await ready(env)
    assert snapshot["status"] == "ready_for_report" and snapshot["can_report"]
    assert snapshot["version"] == 12
    assert len([m for m in snapshot["messages"] if m["role"] == "user"]) == 11
    snapshot, events, _ = await send(env, snapshot, "report")
    assert snapshot["status"] == "completed" and snapshot["version"] == 13
    archive = await env.service.archive(env.ctx, snapshot["consultation_id"])
    assert archive["diagnosis_result"] == snapshot["report"]
    assert archive["conversation_log"].startswith("AI: 【假问题】")
    assert "User: 测试回答\nAI: " in archive["conversation_log"]
    assert events[-1].data["messages"][0]["kind"] == "report"


async def test_gate_supplement_is_saved_and_used_in_report(consultation_env):
    env = consultation_env
    snapshot = await ready(env)
    calls = len(env.transport.calls)
    snapshot, _, _ = await send(env, snapshot, text="还想补充一句")
    assert len(env.transport.calls) == calls
    assert snapshot["status"] == "ready_for_report" and snapshot["version"] == 13
    assert snapshot["messages"][-2]["content"] == "还想补充一句"
    await send(env, snapshot, "report")
    purpose, prompt = env.transport.calls[-1]
    assert purpose == "report" and "患者：还想补充一句" in prompt.user_text


async def test_turn_identity_and_completed_replay(consultation_env):
    env = consultation_env
    snapshot = await env.service.create_or_get(env.ctx, payload())
    snapshot, first, body = await send(env, snapshot, "start")
    handle = await env.service.submit_turn(env.ctx, snapshot["consultation_id"], body)
    replay = [event async for event in env.service.events(handle)]
    assert [e.name for e in replay] == ["accepted", "completed"]
    assert replay[-1] == first[-1]
    with pytest.raises(ConsultationError, match="不同内容") as error:
        await env.service.submit_turn(
            env.ctx,
            snapshot["consultation_id"],
            {**body, "kind": "answer", "text": "other"},
        )
    assert error.value.code == "TURN_ID_CONFLICT"
    snapshot, _, answer = await send(env, snapshot, text="  回答  ")
    handle = await env.service.submit_turn(
        env.ctx, snapshot["consultation_id"], {**answer, "text": "回答"}
    )
    assert handle.result is not None
    with pytest.raises(ConsultationError) as conflict:
        await env.service.submit_turn(
            env.ctx, snapshot["consultation_id"], {**answer, "text": "不同的回答"}
        )
    assert conflict.value.code == "TURN_ID_CONFLICT"
    assert (await env.service.get_snapshot(env.ctx, snapshot["consultation_id"]))[
        "version"
    ] == 2


async def test_turn_admission_rules(consultation_env):
    env = consultation_env
    snapshot = await env.service.create_or_get(env.ctx, payload())
    for kind, text, code in [
        ("answer", "x", "INVALID_TURN"),
        ("report", "", "REPORT_NOT_READY"),
    ]:
        with pytest.raises(ConsultationError) as error:
            await env.service.submit_turn(
                env.ctx,
                snapshot["consultation_id"],
                {
                    "turn_id": str(uuid4()),
                    "kind": kind,
                    "text": text,
                    "base_version": 0,
                },
            )
        assert error.value.code == code
    snapshot, _, _ = await send(env, snapshot, "start")
    for text in ("  ", "字" * 2001):
        with pytest.raises(ConsultationError) as error:
            await env.service.submit_turn(
                env.ctx,
                snapshot["consultation_id"],
                {
                    "turn_id": str(uuid4()),
                    "kind": "answer",
                    "text": text,
                    "base_version": 1,
                },
            )
        assert error.value.code == "INVALID_TURN"
    with pytest.raises(ConsultationError) as error:
        await env.service.submit_turn(
            env.ctx,
            snapshot["consultation_id"],
            {"turn_id": str(uuid4()), "kind": "start", "base_version": 1},
        )
    assert error.value.code == "INVALID_TURN"


async def test_inputs_update_only_before_start(consultation_env):
    env = consultation_env
    body = payload()
    first = await env.service.create_or_get(env.ctx, body)
    body["inputs"]["patient"]["sex"] = "女"
    second = await env.service.create_or_get(env.ctx, body)
    assert second["consultation_id"] == first["consultation_id"]
    snapshot, _, _ = await send(env, second, "start")
    body["inputs"]["patient"]["sex"] = "男"
    await env.service.create_or_get(env.ctx, body)
    async with env.sessions() as db:
        stored = await db.scalar(select(Consultation))
        assert stored.inputs["patient"]["sex"] == "女"
        assert "- 性别: 女" in stored.user_input_text
        assert stored.workflow_state["age_basis_date"]
