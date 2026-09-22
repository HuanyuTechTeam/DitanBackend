"""Organization isolation through HTTP routes and repository entry points."""

from copy import deepcopy
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import select, func

from app.core.auth import create_access_token
from app.core.config import get_settings
from app.core.exceptions import NotFoundException
from app.core.organization import OrganizationContext
from app.models import (
    Doctor,
    Patient,
    PreDiagnosisRecord,
    ChatConversation,
    ChatMessage,
)
from app.repositories import (
    PatientRepository,
    MedicalRecordRepository,
    PreDiagnosisRepository,
    SanzhenRepository,
    AIDiagnosisRepository,
)
from app.services.diagnosis_service import DiagnosisService
from tests.org_helpers import upload_body


@pytest.fixture
async def org_doctors(db_session):
    doctors = {}
    for index, (name, org) in enumerate(
        [("a", "org-a"), ("a_peer", "org-a"), ("b", "org-b"), ("legacy", None)]
    ):
        doctor = Doctor(
            username=f"synthetic_{name}",
            password_hash="unused-synthetic-hash",
            name=f"Doctor {name}",
            gender="OTHER",
            phone=f"1390013900{index}",
            apkio_org_id=org,
            apkio_user_id=f"doctor-{name}" if org else None,
        )
        db_session.add(doctor)
        doctors[name] = doctor
    await db_session.commit()
    return {
        name: {
            "Authorization": "Bearer "
            + create_access_token(
                {"doctor_id": doc.doctor_id, "username": doc.username}
            )
        }
        for name, doc in doctors.items()
    }


@pytest.fixture
async def org_records(client, verifier, monkeypatch):
    body = upload_body()
    result = {}
    for org in ("a", "b"):
        response = await client.post(
            "/api/v1/medical-record",
            json=body,
            headers={"Authorization": f"Bearer upload-{org}"},
        )
        assert response.status_code == 201
        result[org] = response.json()["data"]
    with monkeypatch.context() as legacy:
        legacy.setattr(get_settings(), "MEDICAL_UPLOAD_AUTH_REQUIRED", False)
        response = await client.post("/api/v1/medical-record", json=body)
        assert response.status_code == 201
        result["legacy"] = response.json()["data"]
    return result


async def test_same_phone_and_uuid_are_independent(
    client, db_session, org_doctors, org_records
):
    assert len({r["record_id"] for r in org_records.values()}) == 3
    assert len({r["patient_id"] for r in org_records.values()}) == 3
    for actor in ("a", "b", "legacy"):
        response = await client.get(
            "/api/v1/patient/query?phone=13800138000", headers=org_doctors[actor]
        )
        assert response.status_code == 200
        assert [r["record_id"] for r in response.json()["data"]["medical_records"]] == [
            org_records[actor]["record_id"]
        ]
    assert await db_session.scalar(select(func.count()).select_from(Patient)) == 3
    assert (
        await db_session.scalar(select(func.count()).select_from(PreDiagnosisRecord))
        == 3
    )


@pytest.mark.parametrize(
    ("actor", "target"), [("a", "b"), ("b", "a"), ("a", "legacy"), ("legacy", "a")]
)
async def test_cross_org_record_read_confirm_diagnosis_and_ai(
    client, org_doctors, org_records, actor, target
):
    record_id = org_records[target]["record_id"]
    headers = org_doctors[actor]
    with patch("app.api.patient.get_tcm_service") as ai:
        for suffix, method, body in [
            ("", "GET", None),
            ("/confirm", "POST", {}),
            ("/ai-diagnosis", "POST", {"asr_text": "synthetic"}),
            ("/ai-diagnosis/stream", "POST", {"asr_text": "synthetic"}),
            ("/doctor-diagnosis", "POST", {"comments": "synthetic"}),
        ]:
            url = f"/api/v1/medical-record/{record_id}{suffix}"
            response = await client.request(method, url, json=body, headers=headers)
            missing = await client.request(
                method,
                f"/api/v1/medical-record/999999{suffix}",
                json=body,
                headers=headers,
            )
            assert response.status_code == missing.status_code == 404
            assert "text/event-stream" not in response.headers.get("content-type", "")
            assert "Synthetic patient" not in response.text
            assert "13800138000" not in response.text
        ai.assert_not_called()


async def test_phone_query_does_not_fall_back_to_legacy_or_other_org(
    client, verifier, org_doctors
):
    body = upload_body()
    response = await client.post(
        "/api/v1/medical-record",
        json=body,
        headers={"Authorization": "Bearer upload-b"},
    )
    assert response.status_code == 201
    for actor in ("a", "legacy"):
        assert (
            await client.get(
                "/api/v1/patient/query?phone=13800138000", headers=org_doctors[actor]
            )
        ).status_code == 404


async def test_diagnosis_details_updates_and_doctor_ownership(
    client, org_records, org_doctors
):
    record_id = org_records["a"]["record_id"]
    response = await client.post(
        f"/api/v1/medical-record/{record_id}/doctor-diagnosis",
        json={"comments": "initial"},
        headers=org_doctors["a"],
    )
    assert response.status_code == 201
    diagnosis_id = response.json()["data"]["diagnosis_id"]
    url = f"/api/v1/doctor-diagnosis/{diagnosis_id}"
    for actor in ("b", "legacy"):
        assert (await client.get(url, headers=org_doctors[actor])).status_code == 404
        assert (
            await client.put(
                url, json={"comments": "forbidden"}, headers=org_doctors[actor]
            )
        ).status_code == 404
    assert (await client.get(url, headers=org_doctors["a_peer"])).status_code == 200
    assert (
        await client.put(
            url, json={"comments": "forbidden"}, headers=org_doctors["a_peer"]
        )
    ).status_code == 400
    assert (
        await client.put(url, json={"comments": "updated"}, headers=org_doctors["a"])
    ).status_code == 200
    assert (
        await client.post(
            f"/api/v1/medical-record/{record_id}/confirm", headers=org_doctors["a"]
        )
    ).status_code == 200
    assert (
        await client.put(
            url, json={"comments": "after confirmation"}, headers=org_doctors["a"]
        )
    ).status_code == 400


async def test_ai_diagnosis_cannot_be_copied_across_organizations(
    client, db_session, org_records, org_doctors
):
    ai = await AIDiagnosisRepository(
        db_session, OrganizationContext("org-b")
    ).create_ai_diagnosis(
        record_id=org_records["b"]["record_id"],
        formatted_medical_record="synthetic-private-b",
    )
    await db_session.commit()
    response = await client.post(
        f"/api/v1/medical-record/{org_records['a']['record_id']}/doctor-diagnosis",
        json={"based_on_ai_diagnosis_id": ai.diagnosis_id},
        headers=org_doctors["a"],
    )
    assert response.status_code == 404
    assert "synthetic-private-b" not in response.text


async def test_replay_does_not_modify_generated_diagnosis(
    client, verifier, org_doctors
):
    body = upload_body()
    original = await client.post(
        "/api/v1/medical-record",
        json=body,
        headers={"Authorization": "Bearer upload-a"},
    )
    record_id = original.json()["data"]["record_id"]
    diagnosis = await client.post(
        f"/api/v1/medical-record/{record_id}/doctor-diagnosis",
        json={"comments": "keep-this-diagnosis"},
        headers=org_doctors["a"],
    )
    retry = await client.post(
        "/api/v1/medical-record",
        json=deepcopy(body),
        headers={"Authorization": "Bearer upload-a"},
    )
    assert retry.status_code == 201
    stored = await client.get(
        f"/api/v1/doctor-diagnosis/{diagnosis.json()['data']['diagnosis_id']}",
        headers=org_doctors["a"],
    )
    assert stored.json()["data"]["comments"] == "keep-this-diagnosis"
    assert retry.json()["data"]["status"] == "in_progress"


@pytest.mark.parametrize("actor", ["b", "legacy"])
async def test_all_chat_access_is_scoped_including_unlinked_conversations(
    client, db_session, org_records, org_doctors, actor
):
    for patient_id in (None, org_records["a"]["patient_id"]):
        created = await client.post(
            "/api/v1/chat/conversation",
            json={"patient_id": patient_id},
            headers=org_doctors["a"],
        )
        assert created.status_code == 201
        session = created.json()["data"]["session_id"]
        with patch("app.services.chat_service.OpenAIChatCompletion") as ai:
            assert (
                await client.get(
                    f"/api/v1/chat/conversation/{session}", headers=org_doctors[actor]
                )
            ).status_code == 404
            for path in ("/api/v1/chat/chat", "/api/v1/chat/chat/stream"):
                response = await client.post(
                    path,
                    json={"session_id": session, "content": "do not send"},
                    headers=org_doctors[actor],
                )
                assert response.status_code == 404
            assert (
                await client.delete(
                    f"/api/v1/chat/conversation/{session}", headers=org_doctors[actor]
                )
            ).status_code == 404
            ai.assert_not_called()
        assert (
            await client.get(
                f"/api/v1/chat/conversation/{session}", headers=org_doctors["a"]
            )
        ).status_code == 200
    assert await db_session.scalar(select(func.count()).select_from(ChatMessage)) == 0


async def test_chat_patient_link_must_be_same_org(client, org_records, org_doctors):
    response = await client.post(
        "/api/v1/chat/conversation",
        json={"patient_id": org_records["b"]["patient_id"]},
        headers=org_doctors["a"],
    )
    assert response.status_code == 404


@pytest.mark.parametrize("authorization", [None, "Bearer upload-a"])
async def test_chat_and_patient_read_require_doctor_not_upload_scope(
    client, verifier, org_records, authorization
):
    headers = {} if authorization is None else {"Authorization": authorization}
    for method, url, body in [
        ("POST", "/api/v1/chat/conversation", {}),
        ("GET", "/api/v1/chat/conversation/unknown", None),
        (
            "POST",
            "/api/v1/chat/chat",
            {"session_id": "unknown", "content": "synthetic"},
        ),
        (
            "POST",
            "/api/v1/chat/chat/stream",
            {"session_id": "unknown", "content": "synthetic"},
        ),
        ("DELETE", "/api/v1/chat/conversation/unknown", None),
        ("GET", f"/api/v1/medical-record/{org_records['a']['record_id']}", None),
        (
            "POST",
            f"/api/v1/medical-record/{org_records['a']['record_id']}/ai-diagnosis",
            {"asr_text": "synthetic"},
        ),
    ]:
        assert (
            await client.request(method, url, json=body, headers=headers)
        ).status_code == 401


async def test_legacy_chat_only_accessible_to_unbound_doctor(
    client, db_session, org_doctors
):
    conversation = ChatConversation(
        org_id="__legacy__",
        session_id="historical-anonymous",
        system_prompt="synthetic-legacy",
    )
    db_session.add(conversation)
    await db_session.flush()
    db_session.add(
        ChatMessage(
            conversation_id=conversation.conversation_id,
            role="USER",
            content="synthetic-old-chat",
        )
    )
    await db_session.commit()
    url = "/api/v1/chat/conversation/historical-anonymous"
    assert (await client.get(url)).status_code == 401
    assert (await client.get(url, headers=org_doctors["a"])).status_code == 404
    result = await client.get(url, headers=org_doctors["legacy"])
    assert result.status_code == 200
    assert result.json()["data"]["messages"][0]["content"] == "synthetic-old-chat"


async def test_repository_list_count_and_parent_write_are_scoped(
    db_session, org_records
):
    scope = OrganizationContext("org-a")
    patients = PatientRepository(db_session, scope)
    assert await patients.count() == 1
    assert len(await patients.get_all()) == 1
    assert await patients.get_by_patient_id(org_records["b"]["patient_id"]) is None
    with pytest.raises(NotFoundException):
        await MedicalRecordRepository(db_session, scope).create_medical_record(
            org_records["b"]["patient_id"], upload_body()["uuid"]
        )
    with pytest.raises(NotFoundException):
        await PreDiagnosisRepository(db_session, scope).create_pre_diagnosis(
            org_records["b"]["record_id"], upload_body()["uuid"]
        )
    with pytest.raises(NotFoundException):
        await SanzhenRepository(db_session, scope).create_sanzhen(
            org_records["b"]["pre_diagnosis"]["pre_diagnosis_id"]
        )
    with pytest.raises(NotFoundException):
        await DiagnosisService(db_session, scope).save_stream_diagnosis_result(
            org_records["b"]["record_id"], {}
        )


async def test_stream_save_uses_fixed_scope_while_another_doctor_logs_in(
    client, db_session, org_records, org_doctors
):
    record_id = org_records["a"]["record_id"]

    async def stream(**kwargs):
        response = await client.get("/api/v1/doctor/me", headers=org_doctors["b"])
        assert response.status_code == 200
        yield 'event: complete\ndata: {"status":"success","formatted_medical_record":"synthetic-stream-a"}\n\n'

    with patch("app.api.patient.get_tcm_service") as ai:
        service = Mock()
        service.stream_complete_diagnosis = stream
        ai.return_value = service
        response = await client.post(
            f"/api/v1/medical-record/{record_id}/ai-diagnosis/stream",
            json={"asr_text": "synthetic"},
            headers=org_doctors["a"],
        )
    assert response.status_code == 200
    assert "event: saved" in response.text
    records = await AIDiagnosisRepository(
        db_session, OrganizationContext("org-a")
    ).get_by_record_id(record_id)
    assert len(records) == 1
    assert records[0].formatted_medical_record == "synthetic-stream-a"
    assert not await AIDiagnosisRepository(
        db_session, OrganizationContext("org-b")
    ).get_by_record_id(record_id)
