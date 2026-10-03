"""Online verification for consultation tickets; no anonymous fallback."""

import re

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.exceptions import ConsultationError
from app.core.upload_auth import UploadAuthError, UploadPrincipal, verify_token

consultation_security = HTTPBearer(auto_error=False, scheme_name="ConsultationToken")


async def get_consultation_principal(
    request: Request,
    _credentials: HTTPAuthorizationCredentials | None = Depends(consultation_security),
) -> UploadPrincipal:
    headers = request.headers.getlist("authorization")
    if len(headers) != 1:
        raise ConsultationError("AUTH_TOKEN_INVALID", 401)
    match = re.fullmatch(r"Bearer ([A-Za-z0-9._~+/-]+=*)", headers[0], re.IGNORECASE)
    if match is None:
        raise ConsultationError("AUTH_TOKEN_INVALID", 401)
    try:
        return await verify_token(
            match.group(1),
            path="/client/consultation/current",
            audience="ditan-consultation",
            scope="consultation:write",
        )
    except UploadAuthError as exc:
        if exc.status_code == 503:
            raise ConsultationError("AUTH_UNAVAILABLE", 503, retryable=True) from None
        code = (
            "AUTH_EXPIRED" if exc.code == "AUTH_TOKEN_EXPIRED" else "AUTH_TOKEN_INVALID"
        )
        raise ConsultationError(code, 401) from None
