from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.services.consultation.llm import ConsultationLLM
from app.services.consultation.llm_fake import FakeTransport
from app.services.consultation.runner import TurnRunner
from app.services.consultation.service import ConsultationService
from tests.org_helpers import principal


def context(org="org-a"):
    identity = principal(org)
    return SimpleNamespace(
        organization=identity.organization, current_consultation=identity
    )


def payload(sex="男", birthday="2000-05-01"):
    return {
        "encounter_uuid": str(uuid4()),
        "pre_diagnosis_uuid": str(uuid4()),
        "inputs": {"patient": {"sex": sex, "birthday": birthday}, "assessments": {}},
    }


def make_environment(engine):
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    transport = FakeTransport()
    llm = ConsultationLLM(transport, sessions)
    runner = TurnRunner(retention=0.05)
    service = ConsultationService(
        sessions, llm=llm, task_runner=runner, poll_interval=0.01, heartbeat=0.02
    )
    return SimpleNamespace(
        engine=engine,
        sessions=sessions,
        transport=transport,
        llm=llm,
        runner=runner,
        service=service,
        ctx=context(),
    )


@pytest.fixture
async def consultation_env(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'consultation.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    env = make_environment(engine)
    try:
        yield env
    finally:
        await env.runner.shutdown(timeout=0.2)
        await engine.dispose()


async def send(env, snapshot, kind="answer", text="测试回答", turn_id=None):
    body = {
        "turn_id": turn_id or str(uuid4()),
        "kind": kind,
        "base_version": snapshot["version"],
    }
    if kind == "answer":
        body["text"] = text
    handle = await env.service.submit_turn(env.ctx, snapshot["consultation_id"], body)
    events = [event async for event in env.service.events(handle)]
    assert events[-1].name == "completed", events
    return (
        await env.service.get_snapshot(env.ctx, snapshot["consultation_id"]),
        events,
        body,
    )


async def ready(env, body=None):
    snapshot = await env.service.create_or_get(env.ctx, body or payload())
    snapshot, _, _ = await send(env, snapshot, "start")
    while snapshot["status"] == "collecting":
        snapshot, _, _ = await send(env, snapshot)
    return snapshot
