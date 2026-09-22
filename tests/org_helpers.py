"""Synthetic upload identities and payloads shared by isolation and PostgreSQL tests."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.core.organization import OrganizationContext
from app.core.upload_auth import UploadPrincipal


def upload_body() -> dict:
    return {
        "uuid": str(uuid4()),
        "patient_phone": "13800138000",
        "patient_info": {
            "name": "Synthetic patient",
            "sex": "MALE",
            "birthday": "1990-01-01",
            "phone": "13800138000",
        },
        "pre_diagnosis": {
            "uuid": str(uuid4()),
            "height": 175,
            "coze_conversation_log": "synthetic-private-clinical-text",
            "sanzhen_analysis": {
                "face": "synthetic-face",
                "face_image_url": "https://invalid.test/synthetic.png",
            },
        },
    }


def identity(org: str = "org-a") -> dict:
    return {
        "requestId": "apkio-test-request",
        "code": "OK",
        "message": "success",
        "data": {
            "active": True,
            "audience": "ditan-medical-upload",
            "scope": ["medical-record:write"],
            "orgId": org,
            "userId": "operator-a",
            "deviceId": "device-a",
            "clientSessionId": "session-a",
            "expiresAt": (
                datetime.now(timezone.utc) + timedelta(minutes=4)
            ).isoformat(),
        },
    }


def principal(org: str = "org-a", user: str = "operator-a") -> UploadPrincipal:
    return UploadPrincipal(
        OrganizationContext(org),
        user,
        "device-a",
        "session-a",
        datetime.now(timezone.utc) + timedelta(minutes=4),
    )
