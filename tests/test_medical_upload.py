"""Upload authorization, normalization, atomicity and safe auditing."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.models import (
    Patient,
    PatientMedicalRecord,
    PreDiagnosisRecord,
    SanzhenAnalysisResult,
    Doctor,
)
from tests.org_helpers import upload_body, identity

UPLOAD = "/api/v1/medical-record"
HEADERS = {"Authorization": "Bearer upload-a"}
BUSINESS_MODELS = (
    Patient,
    PatientMedicalRecord,
    PreDiagnosisRecord,
    SanzhenAnalysisResult,
)


async def counts(db):
    return [
        await db.scalar(select(func.count()).select_from(model))
        for model in BUSINESS_MODELS
    ]


@pytest.mark.parametrize(
    "authorization", [None, "", "Bearer", "Bearer ", "Basic opaque", "Bearer bad token"]
)
async def test_strict_missing_or_malformed_authorization(
    client, db_session, verifier, authorization
):
    headers = {} if authorization is None else {"Authorization": authorization}
    response = await client.post(UPLOAD, json=upload_body(), headers=headers)
    assert response.status_code == 401
    assert response.json()["success"] is False
    assert response.json()["requestId"] == response.headers["x-request-id"]
    assert await counts(db_session) == [0, 0, 0, 0]
    assert not verifier.requests


async def test_repeated_authorization_header_is_rejected(client, db_session, verifier):
    response = await client.post(
        UPLOAD,
        json=upload_body(),
        headers=[
            ("Authorization", "Bearer upload-a"),
            ("Authorization", "Bearer upload-b"),
        ],
    )
    assert response.status_code == 401
    assert await counts(db_session) == [0, 0, 0, 0]


@pytest.mark.parametrize(
    "token",
    ["user-token", "device-token", "client-session-token", "forged.jwt.signature"],
)
async def test_other_credential_types_never_grant_upload(
    client, db_session, verifier, token
):
    response = await client.post(
        UPLOAD, json=upload_body(), headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401
    assert await counts(db_session) == [0, 0, 0, 0]
    assert await db_session.scalar(select(func.count()).select_from(Doctor)) == 0


async def test_local_doctor_token_cannot_upload(
    client, db_session, verifier, auth_headers
):
    response = await client.post(UPLOAD, json=upload_body(), headers=auth_headers)
    assert response.status_code == 401
    assert await counts(db_session) == [0, 0, 0, 0]


async def test_legacy_only_when_authorization_completely_absent(
    client, db_session, verifier, monkeypatch
):
    monkeypatch.setattr(get_settings(), "MEDICAL_UPLOAD_AUTH_REQUIRED", False)
    body = upload_body()
    success = await client.post(UPLOAD, json=body)
    assert success.status_code == 201
    row = await db_session.scalar(select(PatientMedicalRecord))
    assert row.org_id == "__legacy__"
    for token in ("", "Bearer wrong-token", "Basic invalid"):
        failed = await client.post(
            UPLOAD, json=upload_body(), headers={"Authorization": token}
        )
        assert failed.status_code == 401
    assert await counts(db_session) == [1, 1, 1, 1]


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("active", False, 401),
        ("active", "true", 503),
        ("audience", "org", 401),
        ("scope", [], 401),
        ("scope", "medical-record:write", 503),
        ("orgId", "", 503),
        ("orgId", "__legacy__", 503),
        ("orgId", 1, 503),
        ("userId", None, 503),
        ("deviceId", " ", 503),
        ("clientSessionId", [], 503),
        ("expiresAt", "2020-01-01T00:00:00+00:00", 401),
        ("expiresAt", "2999-01-01T00:00:00", 503),
        ("expiresAt", "invalid", 503),
    ],
)
async def test_verification_identity_must_match_protocol(
    client, db_session, verifier, field, value, expected
):
    envelope = identity()
    envelope["data"][field] = value
    verifier.responses["upload-a"] = httpx.Response(200, json=envelope)
    response = await client.post(UPLOAD, json=upload_body(), headers=HEADERS)
    assert response.status_code == expected
    assert await counts(db_session) == [0, 0, 0, 0]


@pytest.mark.parametrize(
    "field",
    [
        "active",
        "audience",
        "scope",
        "orgId",
        "userId",
        "deviceId",
        "clientSessionId",
        "expiresAt",
    ],
)
async def test_missing_identity_fields_fail_closed(client, db_session, verifier, field):
    envelope = identity()
    del envelope["data"][field]
    verifier.responses["upload-a"] = httpx.Response(200, json=envelope)
    assert (
        await client.post(UPLOAD, json=upload_body(), headers=HEADERS)
    ).status_code == 503
    assert await counts(db_session) == [0, 0, 0, 0]


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"code": "OK"},
        {"requestId": "r", "code": "DENIED", "message": "bad", "data": {}},
    ],
)
async def test_malformed_envelopes(client, db_session, verifier, payload):
    verifier.responses["upload-a"] = httpx.Response(200, content=json.dumps(payload))
    assert (
        await client.post(UPLOAD, json=upload_body(), headers=HEADERS)
    ).status_code == 503
    assert await counts(db_session) == [0, 0, 0, 0]


@pytest.mark.parametrize("status", [301, 302, 307, 308, 429, 500, 502, 503])
async def test_unavailable_or_redirected_verifier(client, db_session, verifier, status):
    verifier.responses["upload-a"] = httpx.Response(
        status, headers={"Location": "https://untrusted.invalid/"}
    )
    response = await client.post(UPLOAD, json=upload_body(), headers=HEADERS)
    assert response.status_code == 503
    assert len(verifier.requests) == 1
    assert await counts(db_session) == [0, 0, 0, 0]


@pytest.mark.parametrize("status", [200, 401, 403])
async def test_non_json_responses_fail_closed(client, db_session, verifier, status):
    verifier.responses["upload-a"] = httpx.Response(
        status, content=b"<html>bad gateway</html>"
    )
    assert (
        await client.post(UPLOAD, json=upload_body(), headers=HEADERS)
    ).status_code == 503
    assert await counts(db_session) == [0, 0, 0, 0]


@pytest.mark.parametrize(
    "error_type",
    [
        httpx.ConnectError,
        httpx.ConnectTimeout,
        httpx.ReadTimeout,
        httpx.RemoteProtocolError,
        TimeoutError,
    ],
)
async def test_network_errors_are_retryable_and_redacted(
    client, db_session, verifier, error_type, caplog
):
    verifier.error = error_type("upload-a 13800138000 synthetic-private-clinical-text")
    response = await client.post(UPLOAD, json=upload_body(), headers=HEADERS)
    assert response.status_code == 503
    assert "upload-a" not in response.text + caplog.text
    assert "13800138000" not in response.text + caplog.text
    assert await counts(db_session) == [0, 0, 0, 0]


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "AUTH_TOKEN_INVALID"),
        (401, "AUTH_TOKEN_EXPIRED"),
        (403, "ORG_DISABLED"),
        (403, "DEVICE_UNBOUND"),
        (403, "LICENSE_DISABLED"),
    ],
)
async def test_explicit_auth_denials(client, db_session, verifier, status, code):
    verifier.responses["upload-a"] = httpx.Response(
        status,
        json={
            "requestId": "remote-r",
            "code": code,
            "message": "untrusted-upload-a",
            "data": None,
        },
    )
    response = await client.post(UPLOAD, json=upload_body(), headers=HEADERS)
    assert response.status_code == status
    assert response.json()["code"] == code
    assert "untrusted-upload-a" not in response.text
    assert await counts(db_session) == [0, 0, 0, 0]


@pytest.mark.parametrize(
    ("url", "allow", "expected"),
    [
        ("https://apkio.invalid/api", False, 201),
        ("http://127.0.0.1:8000/api", True, 201),
        ("http://[::1]:8000/api", True, 201),
        ("http://127.0.0.1:8000/api", False, 503),
        ("http://apkio.invalid/api", True, 503),
        ("https://apkio.invalid", False, 503),
        ("https://user:password@apkio.invalid/api", False, 503),
        ("https://apkio.invalid/api?redirect=evil", False, 503),
    ],
)
async def test_verification_destination_policy(
    client, verifier, monkeypatch, url, allow, expected
):
    monkeypatch.setattr(get_settings(), "APKIO_BASE_URL", url)
    monkeypatch.setattr(get_settings(), "APKIO_ALLOW_LOOPBACK_HTTP", allow)
    response = await client.post(UPLOAD, json=upload_body(), headers=HEADERS)
    assert response.status_code == expected
    if expected == 201:
        assert str(verifier.requests[0].url) == url + "/client/medical-upload/current"


async def test_authoritative_identity_and_first_uploader_survive_retries(
    client, db_session, verifier, caplog
):
    body = upload_body()
    body["orgId"] = "attacker-org"
    body["userId"] = "attacker-user"
    headers = dict(
        HEADERS, **{"X-Org-Id": "attacker-org", "X-Request-Id": "untrusted-id"}
    )
    first = await client.post(
        UPLOAD + "?orgId=attacker-org", json=body, headers=headers
    )
    assert first.status_code == 201
    second_identity = identity()
    second_identity["data"]["userId"] = "operator-second"
    verifier.responses["upload-a"] = httpx.Response(200, json=second_identity)
    body = dict(reversed(list(body.items())))
    body["pre_diagnosis"]["weight"] = None
    second = await client.post(UPLOAD, json=body, headers=HEADERS)
    assert second.status_code == 201
    assert first.json()["data"]["record_id"] == second.json()["data"]["record_id"]
    assert len(verifier.requests) == 2
    record = await db_session.scalar(select(PatientMedicalRecord))
    assert record.org_id == "org-a"
    assert record.upload_user_id == "operator-a"
    assert record.upload_request_id == first.headers["x-request-id"]
    assert record.upload_request_id != "untrusted-id"
    assert await db_session.scalar(select(func.count()).select_from(Doctor)) == 0
    audits = [r.extra_data for r in caplog.records if r.name == "medical_upload.audit"]
    assert [a["result"] for a in audits] == ["created", "replayed"]
    assert audits[1]["userId"] == "operator-second"
    for secret in (
        "upload-a",
        body["patient_phone"],
        "synthetic-private-clinical-text",
    ):
        assert secret not in caplog.text
    assert await counts(db_session) == [1, 1, 1, 1]


@pytest.mark.parametrize(
    "change", ["patient", "clinical", "image", "pre_uuid", "missing_info"]
)
async def test_same_uuid_different_content_conflicts(
    client, db_session, verifier, change
):
    body = upload_body()
    first = await client.post(UPLOAD, json=body, headers=HEADERS)
    changed = deepcopy(body)
    if change == "patient":
        changed["patient_info"]["name"] = "changed"
    elif change == "clinical":
        changed["pre_diagnosis"]["coze_conversation_log"] = "changed"
    elif change == "image":
        changed["pre_diagnosis"]["sanzhen_analysis"]["face_image_url"] = (
            "https://invalid.test/changed"
        )
    elif change == "pre_uuid":
        changed["pre_diagnosis"]["uuid"] = upload_body()["pre_diagnosis"]["uuid"]
    else:
        del changed["patient_info"]
    second = await client.post(UPLOAD, json=changed, headers=HEADERS)
    assert first.status_code == 201
    assert second.status_code == 409
    assert await counts(db_session) == [1, 1, 1, 1]
    patient = await db_session.scalar(select(Patient))
    assert patient.name == body["patient_info"]["name"]


async def test_historical_record_without_digest_is_not_guessed(
    client, db_session, verifier
):
    body = upload_body()
    await client.post(UPLOAD, json=body, headers=HEADERS)
    record = await db_session.scalar(select(PatientMedicalRecord))
    record.upload_digest = None
    await db_session.commit()
    assert (await client.post(UPLOAD, json=body, headers=HEADERS)).status_code == 409
    assert await counts(db_session) == [1, 1, 1, 1]


async def test_duplicate_pre_diagnosis_rolls_back_new_patient(
    client, db_session, verifier
):
    body = upload_body()
    assert (await client.post(UPLOAD, json=body, headers=HEADERS)).status_code == 201
    changed = upload_body()
    changed["patient_phone"] = changed["patient_info"]["phone"] = "13800138001"
    changed["pre_diagnosis"]["uuid"] = body["pre_diagnosis"]["uuid"]
    assert (await client.post(UPLOAD, json=changed, headers=HEADERS)).status_code == 409
    assert await counts(db_session) == [1, 1, 1, 1]


async def test_mid_transaction_failure_rolls_back_and_redacts(
    client, db_session, verifier, caplog
):
    with patch(
        "app.repositories.medical_record_repository.SanzhenRepository.create_sanzhen",
        new=AsyncMock(
            side_effect=RuntimeError("synthetic-private-clinical-text 13800138000")
        ),
    ):
        response = await client.post(UPLOAD, json=upload_body(), headers=HEADERS)
    assert response.status_code == 500
    assert "synthetic-private-clinical-text" not in response.text + caplog.text
    assert await counts(db_session) == [0, 0, 0, 0]


async def test_inconsistent_phone_rejected_before_writes(client, db_session, verifier):
    body = upload_body()
    body["patient_info"]["phone"] = "13800138001"
    assert (await client.post(UPLOAD, json=body, headers=HEADERS)).status_code == 422
    assert await counts(db_session) == [0, 0, 0, 0]


async def test_retry_revalidates_after_source_revocation(client, db_session, verifier):
    body = upload_body()
    first = await client.post(UPLOAD, json=body, headers=HEADERS)
    assert first.status_code == 201
    verifier.responses["upload-a"] = httpx.Response(
        401,
        json={
            "requestId": "revoked",
            "code": "AUTH_TOKEN_EXPIRED",
            "message": "expired",
            "data": None,
        },
    )
    retry = await client.post(UPLOAD, json=body, headers=HEADERS)
    assert retry.status_code == 401
    assert len(verifier.requests) == 2
    assert await counts(db_session) == [1, 1, 1, 1]


async def test_z_timezone_accepted(client, verifier):
    envelope = identity()
    envelope["data"]["expiresAt"] = (
        (datetime.now(timezone.utc) + timedelta(minutes=2))
        .isoformat()
        .replace("+00:00", "Z")
    )
    verifier.responses["upload-a"] = httpx.Response(200, json=envelope)
    assert (
        await client.post(UPLOAD, json=upload_body(), headers=HEADERS)
    ).status_code == 201


async def test_complete_network_phase_has_a_deadline(
    client, db_session, verifier, monkeypatch
):
    import asyncio
    import time

    async def blocked_response(request):
        await asyncio.sleep(30)
        return httpx.Response(200, json=identity())

    monkeypatch.setattr(verifier, "handle", blocked_response)
    started = time.monotonic()
    response = await client.post(UPLOAD, json=upload_body(), headers=HEADERS)
    assert response.status_code == 503
    assert time.monotonic() - started < 8
    assert await counts(db_session) == [0, 0, 0, 0]
