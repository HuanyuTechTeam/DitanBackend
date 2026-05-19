"""Apkio 统一认证接入测试。"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.auth as auth_module
from app.core import hash_password
from app.models import Doctor

APKIO_SECRET = "apkio-test-secret"
APKIO_ORG_ID = "org-00000000-0000-0000-0000-000000000001"
APKIO_USER_ID = "user-00000000-0000-0000-0000-000000000001"
APKIO_EMAIL = "doctor@apkio.test"


def enable_apkio_auth(
    monkeypatch: pytest.MonkeyPatch, *, auto_create_doctor: bool = True
) -> None:
    test_settings = auth_module.settings.model_copy(
        update={
            "APKIO_AUTH_ENABLED": True,
            "APKIO_JWT_SECRET_KEY": APKIO_SECRET,
            "APKIO_JWT_ALGORITHM": "HS256",
            "APKIO_ORG_TOKEN_AUDIENCE": "org",
            "APKIO_REQUIRED_PERMISSION": "ditan.access",
            "APKIO_AUTO_CREATE_DOCTOR": auto_create_doctor,
        }
    )
    monkeypatch.setattr(auth_module, "settings", test_settings)


def create_apkio_token(
    *,
    audience: str = "org",
    org_id: str = APKIO_ORG_ID,
    user_id: str = APKIO_USER_ID,
    email: str = APKIO_EMAIL,
    permissions: dict[str, str] | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": user_id,
        "aud": audience,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
        "jti": "test-jti",
        "email": email,
        "orgId": org_id,
        "roles": ["ditan_doctor"],
        "permissions": permissions if permissions is not None else {"ditan.access": "org"},
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, APKIO_SECRET, algorithm="HS256")


async def create_bound_doctor(db_session: AsyncSession) -> Doctor:
    doctor = Doctor(
        username="apkio_doctor",
        password_hash=hash_password("password123"),
        name="统一认证医生",
        gender="MALE",
        phone="13900139001",
        department="中医科",
        position="主治医师",
        apkio_org_id=APKIO_ORG_ID,
        apkio_user_id=APKIO_USER_ID,
        apkio_email=APKIO_EMAIL,
    )
    db_session.add(doctor)
    await db_session.commit()
    await db_session.refresh(doctor)
    return doctor


@pytest.mark.asyncio
async def test_apkio_org_token_can_access_current_doctor(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    enable_apkio_auth(monkeypatch)
    doctor = await create_bound_doctor(db_session)

    response = await client.get(
        "/api/v1/doctor/me",
        headers={"Authorization": f"Bearer {create_apkio_token()}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["data"]["doctor_id"] == doctor.doctor_id
    assert data["data"]["name"] == "统一认证医生"


@pytest.mark.asyncio
async def test_apkio_org_token_requires_ditan_permission(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    enable_apkio_auth(monkeypatch)
    await create_bound_doctor(db_session)

    response = await client.get(
        "/api/v1/doctor/me",
        headers={"Authorization": f"Bearer {create_apkio_token(permissions={})}"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "缺少 Ditan 访问权限"


@pytest.mark.asyncio
async def test_apkio_org_token_auto_creates_doctor(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    enable_apkio_auth(monkeypatch)

    response = await client.get(
        "/api/v1/doctor/me",
        headers={
            "Authorization": f"Bearer {create_apkio_token(extra_claims={'displayName': 'xsl'})}"
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["username"].startswith("apkio_")
    assert data["name"] == "xsl"
    assert data["gender"] == "OTHER"
    assert data["phone"].startswith("19")
    assert len(data["phone"]) == 11

    doctor = await db_session.scalar(
        select(Doctor).where(
            Doctor.apkio_org_id == APKIO_ORG_ID,
            Doctor.apkio_user_id == APKIO_USER_ID,
        )
    )
    assert doctor is not None
    assert doctor.apkio_email == APKIO_EMAIL


@pytest.mark.asyncio
async def test_apkio_org_token_can_disable_auto_create_doctor(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    enable_apkio_auth(monkeypatch, auto_create_doctor=False)

    response = await client.get(
        "/api/v1/doctor/me",
        headers={"Authorization": f"Bearer {create_apkio_token()}"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Apkio 账号未绑定医生身份"


@pytest.mark.asyncio
async def test_apkio_org_token_rejects_wrong_audience(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    enable_apkio_auth(monkeypatch)
    await create_bound_doctor(db_session)

    response = await client.get(
        "/api/v1/doctor/me",
        headers={"Authorization": f"Bearer {create_apkio_token(audience='platform')}"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "无效的认证凭证"
