"""One credential-free audit event for every upload attempt, including rejected bodies."""

from uuid import uuid4
from starlette.types import ASGIApp, Scope, Receive, Send, Message
from app.core.logging import get_structured_logger

logger = get_structured_logger("medical_upload.audit")


class MedicalUploadAuditMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or scope["path"] != "/api/v1/medical-record"
        ):
            await self.app(scope, receive, send)
            return
        state = scope.setdefault("state", {})
        state["request_id"] = str(uuid4())
        status = 500

        async def send_response(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message.setdefault("headers", []).append(
                    (b"x-request-id", state["request_id"].encode("ascii"))
                )
            await send(message)

        try:
            await self.app(scope, receive, send_response)
        finally:
            principal = state.get("upload_principal")
            logger.info(
                "medical_upload",
                data={
                    "requestId": state["request_id"],
                    "orgId": principal.organization.org_id if principal else None,
                    "userId": principal.user_id if principal else None,
                    "deviceId": principal.device_id if principal else None,
                    "clientSessionId": principal.client_session_id
                    if principal
                    else None,
                    "recordId": state.get("upload_record_id"),
                    "status": status,
                    "result": state.get(
                        "upload_result", "rejected" if status < 500 else "failed"
                    ),
                    "reason": state.get(
                        "upload_failure_code",
                        None if status == 201 else "UPLOAD_FAILED",
                    ),
                },
            )
