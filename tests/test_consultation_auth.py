from copy import deepcopy

import httpx
import pytest
from starlette.requests import Request

from app.core.config import get_settings
from app.core.consultation_auth import get_consultation_principal
from app.core.exceptions import ConsultationError
from tests.org_helpers import identity


def request(headers=None):
    return Request(
        {
            "type": "http",
            "headers": headers
            if headers is not None
            else [(b"authorization", b"Bearer consultation-test")],
        }
    )


@pytest.fixture
def consultation_verifier(monkeypatch):
    payload = deepcopy(identity())
    payload["data"].update(audience="ditan-consultation", scope=["consultation:write"])
    state = {"payload": payload, "status": 200, "error": None, "requests": []}
    monkeypatch.setattr(get_settings(), "APKIO_BASE_URL", "https://apkio.invalid/api")
    real_client = httpx.AsyncClient

    def handle(req):
        state["requests"].append(req)
        assert str(req.url) == "https://apkio.invalid/api/client/consultation/current"
        if state["error"]:
            raise state["error"]
        return httpx.Response(state["status"], json=state["payload"])

    def factory(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        assert kwargs["verify"] is True
        assert kwargs["timeout"].connect == 2
        return real_client(transport=httpx.MockTransport(handle), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return state


async def test_consultation_principal_uses_verified_identity(consultation_verifier):
    principal = await get_consultation_principal(request())
    assert principal.organization.org_id == "org-a"
    assert (principal.user_id, principal.device_id, principal.client_session_id) == (
        "operator-a",
        "device-a",
        "session-a",
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("audience", "ditan-medical-upload"),
        ("scope", []),
        ("active", False),
        ("expiresAt", "2000-01-01T00:00:00+00:00"),
    ],
)
async def test_consultation_rejects_identity(consultation_verifier, field, value):
    consultation_verifier["payload"]["data"][field] = value
    with pytest.raises(ConsultationError) as exc:
        await get_consultation_principal(request())
    assert exc.value.status_code == 401
    assert exc.value.code == (
        "AUTH_EXPIRED" if field == "expiresAt" else "AUTH_TOKEN_INVALID"
    )


@pytest.mark.parametrize("code", ["AUTH_TOKEN_INVALID", "AUTH_TOKEN_EXPIRED"])
async def test_consultation_auth_denied(consultation_verifier, code):
    consultation_verifier.update(
        status=401,
        payload={"requestId": "test", "message": "invalid", "code": code, "data": None},
    )
    with pytest.raises(ConsultationError) as exc:
        await get_consultation_principal(request())
    assert exc.value.status_code == 401
    assert exc.value.code == ("AUTH_EXPIRED" if code.endswith("EXPIRED") else code)


async def test_consultation_auth_timeout(consultation_verifier):
    consultation_verifier["error"] = httpx.ReadTimeout("synthetic timeout")
    with pytest.raises(ConsultationError) as exc:
        await get_consultation_principal(request())
    assert exc.value.status_code == 503
    assert exc.value.data == {"code": "AUTH_UNAVAILABLE", "retryable": True}


@pytest.mark.parametrize(
    "headers",
    [
        [],
        [(b"authorization", b"Basic x")],
        [(b"authorization", b"Bearer")],
        [(b"authorization", b"Bearer a b")],
        [(b"authorization", b"Bearer a"), (b"authorization", b"Bearer a")],
    ],
)
async def test_consultation_never_allows_legacy(headers, monkeypatch):
    monkeypatch.setattr(get_settings(), "MEDICAL_UPLOAD_AUTH_REQUIRED", False)
    with pytest.raises(ConsultationError) as exc:
        await get_consultation_principal(request(headers))
    assert exc.value.status_code == 401
