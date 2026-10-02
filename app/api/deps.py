"""API 依赖注入"""

from typing import Any, Optional
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import get_db, get_current_active_doctor, get_structured_logger
from app.models import Doctor
from app.core.organization import LEGACY_ORG_ID, OrganizationContext
from app.core.upload_auth import UploadPrincipal, get_upload_principal

logger = get_structured_logger(__name__)


class RequestContext:
    """请求上下文"""

    def __init__(
        self,
        request: Request,
        db: AsyncSession,
        doctor: Optional[Doctor] = None,
        upload: Optional[UploadPrincipal] = None,
    ):
        self.request = request
        self.db = db
        self.doctor = doctor
        self.upload = upload
        self._organization = (
            upload.organization
            if upload
            else (
                OrganizationContext(
                    doctor.apkio_org_id
                    if doctor.apkio_org_id is not None
                    else LEGACY_ORG_ID
                )
                if doctor
                else None
            )
        )
        self.method = request.method
        self.path = request.url.path
        self.endpoint = f"{request.method} {request.url.path}"

    @property
    def organization(self) -> OrganizationContext:
        if self._organization is None:
            raise RuntimeError("This operation requires an organization")
        return self._organization

    @property
    def current_upload(self) -> UploadPrincipal:
        if self.upload is None:
            raise RuntimeError("This operation requires an upload principal")
        return self.upload

    @property
    def current_doctor(self) -> Doctor:
        """获取已认证医生。"""
        if self.doctor is None:
            raise RuntimeError(
                "RequestContext does not include an authenticated doctor"
            )
        return self.doctor

    def _build_log_data(self, extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """构建日志数据"""
        data: dict[str, Any] = {
            "method": self.method,
            "path": self.path,
        }
        if self._organization:
            data["org_id"] = self._organization.org_id
        if self.doctor:
            data["doctor_id"] = self.doctor.doctor_id
        if extra:
            data.update(extra)
        return data

    def log_info(self, message: str, **extra: Any):
        """记录信息日志"""
        logger.info(message, data=self._build_log_data(extra if extra else None))

    def log_error(self, message: str, exc: Optional[Exception] = None, **extra: Any):
        """记录错误日志"""
        log_data = self._build_log_data(extra if extra else None)
        if exc:
            log_data["error"] = str(exc)
            logger.error(
                message, data=log_data, exc_info=(type(exc), exc, exc.__traceback__)
            )
        else:
            logger.error(message, data=log_data)

    def log_warning(self, message: str, **extra: Any):
        """记录警告日志"""
        logger.warning(message, data=self._build_log_data(extra if extra else None))

    def log_debug(self, message: str, **extra: Any):
        """记录调试日志"""
        logger.debug(message, data=self._build_log_data(extra if extra else None))


async def get_request_context(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> RequestContext:
    """获取请求上下文（无需认证）"""
    return RequestContext(request=request, db=db)


async def get_auth_context(
    request: Request,
    db: AsyncSession = Depends(get_db),
    doctor: Doctor = Depends(get_current_active_doctor),
) -> RequestContext:
    """获取请求上下文（需要认证）"""
    return RequestContext(request=request, db=db, doctor=doctor)


async def get_upload_context(
    request: Request,
    principal: UploadPrincipal = Depends(get_upload_principal),
    db: AsyncSession = Depends(get_db),
) -> RequestContext:
    return RequestContext(request=request, db=db, upload=principal)
