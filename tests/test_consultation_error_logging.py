from starlette.requests import Request

from app.core.logging import JSONFormatter
from app.services.consultation.runner import TurnRunner
from main import general_exception_handler


def fail_with_private_details():
    private_cause = "SYNTHETIC_PRIVATE_PATIENT"
    private_message = "SYNTHETIC_PRIVATE_PROMPT"
    try:
        raise ValueError(private_cause)
    except ValueError as cause:
        raise RuntimeError(private_message) from cause


def assert_safe_traceback(record):
    assert record.exc_info is not None and record.exc_info[2] is not None
    formatted = JSONFormatter().format(record)
    assert "fail_with_private_details" in formatted
    assert "SYNTHETIC_PRIVATE_PATIENT" not in formatted
    assert "SYNTHETIC_PRIVATE_PROMPT" not in formatted
    assert "RuntimeError" in formatted


async def test_fallback_logs_redacted_exception_with_traceback(caplog):
    request = Request({"type": "http", "path": "/api/v1/consultations", "headers": []})
    try:
        fail_with_private_details()
    except RuntimeError as exc:
        response = await general_exception_handler(request, exc)
    assert response.status_code == 500
    assert_safe_traceback(
        next(
            record
            for record in caplog.records
            if record.message == "Consultation request failed"
        )
    )


async def test_runner_logs_redacted_exception_with_traceback(caplog):
    runner = TurnRunner()

    async def execute(buffer):
        fail_with_private_details()

    buffer = runner.start(("consultation", "turn", 1), execute)
    await runner.shutdown(timeout=0.2)
    assert buffer.events[-1].name == "error"
    record = next(
        record
        for record in caplog.records
        if record.message == "Consultation task failed"
    )
    assert_safe_traceback(record)
    assert record.extra_data == {
        "consultation_id": "consultation",
        "turn_id": "turn",
        "attempt": 1,
    }
