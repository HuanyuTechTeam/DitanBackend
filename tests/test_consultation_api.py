import json
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models.consultation import Consultation
from app.services.consultation.llm_fake import Fault
from app.services.consultation.service import get_service
from main import app
from tests.consultation_helpers import payload, ready
from tests.consultation_helpers import consultation_env as consultation_env
from tests.test_consultation_auth import consultation_verifier as consultation_verifier

ROOT = "/api/v1/consultations"


@pytest.mark.parametrize(
    "value,expected",
    [
        ("男", "男"),
        ("女", "女"),
        ("male", "男"),
        ("MALE", "男"),
        ("mAlE", "男"),
        ("female", "女"),
        ("FEMALE", "女"),
        ("FeMaLe", "女"),
    ],
)
async def test_sex_is_normalized_before_storage(
    consultation_client, consultation_env, value, expected
):
    body = payload(sex=value)
    response = await consultation_client.post(ROOT, json=body)
    assert response.status_code == 200
    async with consultation_env.sessions() as db:
        stored = await db.scalar(
            select(Consultation).where(
                Consultation.id == response.json()["data"]["consultation_id"]
            )
        )
        assert stored.inputs["patient"]["sex"] == expected


@pytest.mark.parametrize("value", ["OTHER", "unknown", "", "male ", " 男", 1, True, []])
async def test_invalid_sex_is_rejected(consultation_client, value):
    response = await consultation_client.post(ROOT, json=payload(sex=value))
    assert response.status_code == 422
    assert response.json()["data"]["code"] == "INVALID_REQUEST"


@pytest.mark.parametrize("omit", [False, True])
async def test_optional_sex_keeps_unknown_branch(consultation_client, omit):
    body = payload(sex=None)
    if omit:
        del body["inputs"]["patient"]["sex"]
    assert (await consultation_client.post(ROOT, json=body)).status_code == 200


async def test_smoke_script_with_fake_provider(consultation_client):
    from scripts.consultation_smoke import smoke

    result = await smoke(consultation_client)
    assert result["disconnect_recovered"]
    assert result["status"] == "completed" and result["answers"] == 11


def parse_events(text):
    result = []
    for frame in text.split("\n\n"):
        if not frame or frame.startswith(":"):
            continue
        lines = frame.splitlines()
        name = next(
            line.removeprefix("event: ") for line in lines if line.startswith("event:")
        )
        data = "\n".join(
            line.removeprefix("data: ") for line in lines if line.startswith("data:")
        )
        result.append((name, json.loads(data)))
    return result


@pytest.fixture
async def consultation_client(consultation_env, consultation_verifier, monkeypatch):
    monkeypatch.setitem(
        app.dependency_overrides, get_service, lambda: consultation_env.service
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": "Bearer consultation-test"},
    ) as client:
        yield client


async def test_consultation_sse_offsets_heartbeat_and_replay(
    consultation_env, consultation_client
):
    env, client = consultation_env, consultation_client
    created = await client.post(ROOT, json=payload())
    assert created.status_code == 200 and created.json()["success"]
    snapshot = created.json()["data"]
    url = f"{ROOT}/{snapshot['consultation_id']}"
    env.transport.faults.append(
        Fault(text="中文𠀀🙂分块内容", chunk_size=2, delay_before=0.05)
    )
    body = {"kind": "start", "turn_id": str(uuid4()), "base_version": 0}
    response = await client.post(url + "/turns", json=body)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    assert ": heartbeat\n\n" in response.text
    events = parse_events(response.text)
    assert events[0][0] == "accepted" and events[-1][0] == "completed"
    offset, text = 0, ""
    for name, data in events:
        if name == "delta":
            assert data["offset"] == offset and data["attempt"] == 1
            offset += len(data["text"])
            text += data["text"]
    assert text == "中文𠀀🙂分块内容"
    assert events[-1][1]["messages"][0]["content"] == text
    retry = parse_events((await client.post(url + "/turns", json=body)).text)
    assert [name for name, _ in retry] == ["accepted", "completed"]
    assert retry[-1] == events[-1]
    saved = (await client.get(url + f"/turns/{body['turn_id']}")).json()["data"]
    assert saved["status"] == "completed" and saved["result"] == events[-1][1]


async def test_admission_errors_are_json_before_stream(consultation_client):
    client = consultation_client
    snapshot = (await client.post(ROOT, json=payload())).json()["data"]
    url = f"{ROOT}/{snapshot['consultation_id']}/turns"
    for body, code in [
        ({"kind": "start", "base_version": 1}, "VERSION_CONFLICT"),
        ({"kind": "report", "base_version": 0}, "REPORT_NOT_READY"),
    ]:
        response = await client.post(url, json={"turn_id": str(uuid4()), **body})
        assert response.status_code == 409
        assert response.headers["content-type"].startswith("application/json")
        data = response.json()["data"]
        assert data["code"] == code
        if code == "VERSION_CONFLICT":
            assert data["snapshot"]["version"] == 0


async def test_busy_response_identifies_pending_turn(
    consultation_env, consultation_client
):
    env, client = consultation_env, consultation_client
    snapshot = (await client.post(ROOT, json=payload())).json()["data"]
    env.transport.faults.append(Fault(delay_before=0.1))
    body = {"turn_id": str(uuid4()), "kind": "start", "base_version": 0}
    await env.service.submit_turn(env.ctx, snapshot["consultation_id"], body)
    response = await client.post(
        f"{ROOT}/{snapshot['consultation_id']}/turns",
        json={**body, "turn_id": str(uuid4())},
    )
    assert response.status_code == 409
    assert response.json()["data"] == {
        "code": "SESSION_BUSY",
        "turn_id": body["turn_id"],
    }


async def test_all_consultation_resources_are_org_scoped(
    consultation_client, consultation_verifier
):
    client = consultation_client
    body = payload()
    snapshot = (await client.post(ROOT, json=body)).json()["data"]
    url = f"{ROOT}/{snapshot['consultation_id']}"
    turn = {"turn_id": str(uuid4()), "kind": "start", "base_version": 0}
    assert (await client.post(url + "/turns", json=turn)).status_code == 200
    consultation_verifier["payload"]["data"]["orgId"] = "org-b"
    for method, path, json_body in [
        ("GET", url, None),
        ("GET", url + f"/turns/{turn['turn_id']}", None),
        ("GET", url + "/archive", None),
        ("POST", url + "/abandon", None),
        ("POST", url + "/turns", turn),
    ]:
        response = await client.request(method, path, json=json_body)
        assert response.status_code == 404, response.text
        assert response.json()["data"]["code"] == "NOT_FOUND"
    other = (await client.post(ROOT, json=body)).json()["data"]
    assert other["consultation_id"] != snapshot["consultation_id"]


async def test_auth_and_validation_use_consultation_envelope(
    consultation_client, monkeypatch
):
    client = consultation_client
    monkeypatch.setattr(get_settings(), "MEDICAL_UPLOAD_AUTH_REQUIRED", False)
    response = await client.post(ROOT, json=payload(), headers={"Authorization": ""})
    assert response.status_code == 401
    assert response.json()["data"]["code"] == "AUTH_TOKEN_INVALID"
    body = payload()
    body["inputs"]["patient"]["name"] = "must_not_reach_model"
    response = await client.post(ROOT, json=body)
    assert response.status_code == 422
    assert response.json()["data"]["code"] == "INVALID_REQUEST"
    assert "must_not_reach_model" not in response.text


async def test_report_archive_and_abandon_routes(consultation_env, consultation_client):
    env, client = consultation_env, consultation_client
    snapshot = await ready(env)
    url = f"{ROOT}/{snapshot['consultation_id']}"
    response = await client.post(
        url + "/turns",
        json={
            "turn_id": str(uuid4()),
            "kind": "report",
            "base_version": snapshot["version"],
        },
    )
    assert parse_events(response.text)[-1][0] == "completed"
    archive = await client.get(url + "/archive")
    assert archive.status_code == 200 and archive.json()["data"]["diagnosis_result"]
    assert "User: " in archive.json()["data"]["conversation_log"]
    another = (await client.post(ROOT, json=payload())).json()["data"]
    url = f"{ROOT}/{another['consultation_id']}"
    for _ in range(2):
        response = await client.post(url + "/abandon")
        assert response.json()["data"]["status"] == "abandoned"
