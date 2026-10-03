"""Online, fail-closed verification of Apkio's dedicated upload credential."""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import ipaddress
import re
from urllib.parse import urlsplit

from fastapi import Request, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import httpx
from pydantic import BaseModel, ConfigDict, StrictBool, StrictStr, ValidationError

from app.core.config import get_settings
from app.core.exceptions import BaseAPIException
from app.core.organization import LEGACY_ORG_ID, OrganizationContext


@dataclass(frozen=True)
class UploadPrincipal:
    organization: OrganizationContext
    user_id: str | None
    device_id: str | None
    client_session_id: str | None
    expires_at: datetime | None


class UploadAuthError(BaseAPIException):
    def __init__(self, status_code: int, code: str):
        self.status_code = status_code
        self.code = code
        messages = {
            401: "上传凭证无效或已过期",
            403: "上传身份已停用",
            503: "上传验票服务暂不可用",
        }
        super().__init__(messages[status_code])


class VerifiedIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    active: StrictBool
    audience: StrictStr
    scope: list[StrictStr]
    orgId: StrictStr
    userId: StrictStr
    deviceId: StrictStr
    clientSessionId: StrictStr
    expiresAt: StrictStr


class VerificationEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requestId: StrictStr
    code: StrictStr
    message: StrictStr
    data: VerifiedIdentity


def verification_url(path: str = "/client/medical-upload/current") -> str:
    settings = get_settings()
    base = settings.APKIO_BASE_URL.rstrip("/")
    try:
        parsed = urlsplit(base)
        local = parsed.hostname == "localhost"
        if parsed.hostname and not local:
            try:
                local = ipaddress.ip_address(parsed.hostname).is_loopback
            except ValueError:
                pass
        if (
            not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path != "/api"
            or not (
                parsed.scheme == "https"
                or (
                    parsed.scheme == "http"
                    and local
                    and settings.APKIO_ALLOW_LOOPBACK_HTTP
                )
            )
        ):
            raise ValueError("Invalid verification endpoint")
        _ = parsed.port
    except ValueError:
        raise UploadAuthError(503, "UPLOAD_AUTH_UNAVAILABLE") from None
    return base + path


async def verify_upload_token(token: str) -> UploadPrincipal:
    return await verify_token(
        token, path="/client/medical-upload/current",
        audience="ditan-medical-upload", scope="medical-record:write",
    )


async def verify_token(
    token: str, *, path: str, audience: str, scope: str
) -> UploadPrincipal:
    """Verify a server-selected ticket contract without changing upload behavior."""
    url = verification_url(path)
    try:
        async with asyncio.timeout(5):
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(5, connect=2),
                follow_redirects=False,
                trust_env=False,
                verify=True,
            ) as client:
                response = await client.get(
                    url, headers={"Authorization": f"Bearer {token}"}
                )
    except (httpx.HTTPError, TimeoutError, ValueError):
        raise UploadAuthError(503, "UPLOAD_AUTH_UNAVAILABLE") from None

    if response.status_code not in (200, 401, 403):
        raise UploadAuthError(503, "UPLOAD_AUTH_UNAVAILABLE")
    try:
        payload = response.json()
    except ValueError:
        raise UploadAuthError(503, "UPLOAD_AUTH_PROTOCOL_ERROR") from None

    if response.status_code in (401, 403):
        if not (
            isinstance(payload, dict)
            and isinstance(payload.get("requestId"), str)
            and payload["requestId"].strip()
            and isinstance(payload.get("message"), str)
            and isinstance(payload.get("code"), str)
            and re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", payload["code"])
            and payload["code"] != "OK"
        ):
            raise UploadAuthError(503, "UPLOAD_AUTH_PROTOCOL_ERROR")
        raise UploadAuthError(response.status_code, payload["code"])

    try:
        envelope = VerificationEnvelope.model_validate(payload)
        identity = envelope.data
        if envelope.code != "OK" or not envelope.requestId.strip():
            raise ValueError("Invalid envelope")
        for value in (
            identity.orgId,
            identity.userId,
            identity.deviceId,
            identity.clientSessionId,
        ):
            if (
                not value.strip()
                or value != value.strip()
                or any(ord(char) < 32 for char in value)
            ):
                raise ValueError("Invalid identity")
        if identity.orgId == LEGACY_ORG_ID:
            raise ValueError("Reserved organization")
        expires_at = datetime.fromisoformat(identity.expiresAt.replace("Z", "+00:00"))
        if expires_at.tzinfo is None or expires_at.utcoffset() is None:
            raise ValueError("Missing timezone")
    except (ValidationError, ValueError, TypeError):
        raise UploadAuthError(503, "UPLOAD_AUTH_PROTOCOL_ERROR") from None
    if (
        not identity.active
        or identity.audience != audience
        or scope not in identity.scope
    ):
        raise UploadAuthError(401, "AUTH_TOKEN_INVALID")
    if expires_at <= datetime.now(timezone.utc):
        raise UploadAuthError(401, "AUTH_TOKEN_EXPIRED")
    return UploadPrincipal(
        OrganizationContext(identity.orgId),
        identity.userId,
        identity.deviceId,
        identity.clientSessionId,
        expires_at,
    )


upload_security = HTTPBearer(auto_error=False, scheme_name="MedicalUploadToken")


async def get_upload_principal(
    request: Request,
    _credentials: HTTPAuthorizationCredentials | None = Depends(upload_security),
) -> UploadPrincipal:
    headers = request.headers.getlist("authorization")
    if not headers and not get_settings().MEDICAL_UPLOAD_AUTH_REQUIRED:
        principal = UploadPrincipal(
            OrganizationContext(LEGACY_ORG_ID), None, None, None, None
        )
    else:
        if len(headers) != 1:
            raise UploadAuthError(401, "AUTH_TOKEN_INVALID")
        match = re.fullmatch(
            r"Bearer ([A-Za-z0-9._~+/-]+=*)", headers[0], re.IGNORECASE
        )
        if match is None:
            raise UploadAuthError(401, "AUTH_TOKEN_INVALID")
        principal = await verify_upload_token(match.group(1))
    request.state.upload_principal = principal
    return principal
