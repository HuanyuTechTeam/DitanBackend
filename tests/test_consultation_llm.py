import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.consultation import Consultation, ConsultationLLMCall
from app.services.consultation.llm import (
    ConsultationLLM,
    Limits,
    ModelUnavailable,
    OpenAITransport,
    Prompt,
)
from app.services.consultation.llm_fake import FakeTransport, Fault


def prompt():
    return Prompt(
        "org-a",
        str(uuid4()),
        str(uuid4()),
        1,
        "core_history",
        "v1:L03",
        "固定说明",
        "患者资料",
        "固定问题？",
    )


async def collect(stream):
    return "".join([text async for text in stream])


class RecordingLLM(ConsultationLLM):
    def __init__(self, transport, **kwargs):
        super().__init__(transport, **kwargs)
        self.logs = []

    async def _audit(self, prompt, purpose, result):
        self.logs.append((prompt, purpose, result))


async def test_openai_request_parameters_and_usage():
    class SDK:
        def __init__(self):
            self.chat = SimpleNamespace(completions=self)
            self.closed = False

        def with_options(self, **kwargs):
            self.options = kwargs
            return self

        async def create(self, **kwargs):
            self.request = kwargs
            return self

        def __aiter__(self):
            async def chunks():
                yield SimpleNamespace(
                    usage=None,
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="问候"))],
                )
                yield SimpleNamespace(
                    usage=SimpleNamespace(prompt_tokens=12, completion_tokens=2),
                    choices=[],
                )

            return chunks()

        async def close(self):
            self.closed = True

    sdk = SDK()
    llm = RecordingLLM(
        OpenAITransport(SimpleNamespace(async_client=sdk, model_name="test-model"))
    )
    item = prompt()
    assert await collect(llm.stream_question(item)) == "问候"
    assert sdk.options == {"max_retries": 0, "timeout": 30}
    assert sdk.request["max_tokens"] == 150
    assert "temperature" not in sdk.request
    assert sdk.request["messages"] == item.messages
    assert len(sdk.request["messages"]) == 2
    assert sdk.request["stream"] is True and sdk.closed
    assert llm.logs[0][2]["prompt_tokens"] == 12
    assert llm.logs[0][2]["completion_tokens"] == 2
    assert llm.logs[0][2]["first_token_ms"] is not None
    await collect(llm.stream_report(item))
    assert "max_tokens" not in sdk.request and "temperature" not in sdk.request


@pytest.mark.parametrize(
    "fault", [Fault(delay_before=0.1), Fault(delay_between=0.1), Fault(text="")]
)
async def test_question_deadlines_and_empty_output(fault):
    transport = FakeTransport([fault])
    llm = RecordingLLM(
        transport, limits=Limits(question_first=0.01, question_total=0.03)
    )
    with pytest.raises(ModelUnavailable):
        await collect(llm.stream_question(prompt()))
    assert len(transport.calls) == 1
    assert llm.logs[0][2]["status"] == "failed"


async def test_question_circuit_breaker():
    transport = FakeTransport([Fault(fail_after=0) for _ in range(3)])
    llm = RecordingLLM(transport)
    for _ in range(4):
        with pytest.raises(ModelUnavailable):
            await collect(llm.stream_question(prompt()))
    assert len(transport.calls) == 3
    llm.open_until = 0
    assert await collect(llm.stream_question(prompt())) == "【假问题】固定问题？"
    assert llm.question_failures == 0


@pytest.mark.parametrize(
    "faults,success,calls",
    [
        ([Fault(fail_after=0)], True, 2),
        ([Fault(fail_after=0), Fault(fail_after=0)], False, 2),
        ([Fault(fail_after=1)], False, 1),
    ],
)
async def test_report_retries_only_before_first_token(faults, success, calls):
    transport = FakeTransport(faults)
    llm = RecordingLLM(transport)
    if success:
        assert (
            await collect(llm.stream_report(prompt())) == "【假报告】问诊资料已保存。"
        )
    else:
        with pytest.raises(ModelUnavailable):
            await collect(llm.stream_report(prompt()))
    assert len(transport.calls) == calls
    assert len(llm.logs) == calls


async def test_report_total_deadline():
    transport = FakeTransport([Fault(delay_before=0.1)])
    llm = RecordingLLM(transport, limits=Limits(report_total=0.01))
    with pytest.raises(ModelUnavailable):
        await collect(llm.stream_report(prompt()))
    assert len(transport.calls) == 1


async def test_concurrency_limits_actual_calls():
    class CountingTransport(FakeTransport):
        active = 0
        peak = 0

        async def stream(self, *args):
            self.active += 1
            self.peak = max(self.peak, self.active)
            try:
                await asyncio.sleep(0.01)
                async for text in super().stream(*args):
                    yield text
            finally:
                self.active -= 1

    transport = CountingTransport()
    llm = RecordingLLM(transport, concurrency=2)
    await asyncio.gather(*(collect(llm.stream_question(prompt())) for _ in range(6)))
    assert transport.peak == 2 and transport.active == 0


async def test_llm_audit_persists_request_response_and_identity(db_session):
    item = prompt()
    db_session.add(
        Consultation(
            id=item.consultation_id,
            org_id=item.org_id,
            encounter_uuid=str(uuid4()),
            inputs={},
            created_by_user_id="user",
            created_by_device_id="device",
        )
    )
    await db_session.commit()
    llm = ConsultationLLM(
        FakeTransport(), async_sessionmaker(db_session.bind, expire_on_commit=False)
    )
    result = await collect(llm.stream_question(item))
    log = await db_session.scalar(select(ConsultationLLMCall))
    assert (
        log.org_id == item.org_id and log.turn_id == item.turn_id and log.attempt == 1
    )
    assert log.request == {"messages": item.messages}
    assert log.response == result and log.status == "succeeded"
    assert log.first_token_ms is not None and log.latency_ms >= 0
    assert log.completion_tokens is not None


async def test_failed_audit_does_not_change_model_result():
    def broken_session():
        raise RuntimeError("synthetic database failure")

    llm = ConsultationLLM(FakeTransport(), broken_session)
    assert await collect(llm.stream_question(prompt())) == "【假问题】固定问题？"
