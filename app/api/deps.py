"""API 依赖注入"""
from typing import Any, Optional
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import get_db, get_current_active_doctor, get_structured_logger
from app.models import Doctor

logger = get_structured_logger(__name__)


class RequestContext:
    """请求上下文"""

    def __init__(self, request: Request, db: AsyncSession, doctor: Doctor = None):
        self.request = request
        self.db = db
        self.doctor = doctor
        self.method = request.method
        self.path = request.url.path
        self.endpoint = f"{request.method} {request.url.path}"

    def _build_log_data(self, extra: Optional[dict] = None) -> dict:
        """构建日志数据"""
        data = {
            "method": self.method,
            "path": self.path,
        }
        if self.doctor:
            data["doctor_id"] = self.doctor.doctor_id
        if extra:
            data.update(extra)
        return data

    def log_info(self, message: str, **extra: Any):
        """记录信息日志"""
        logger.info(message, data=self._build_log_data(extra if extra else None))

    def log_error(self, message: str, exc: Exception = None, **extra: Any):
        """记录错误日志"""
        log_data = self._build_log_data(extra if extra else None)
        if exc:
            log_data["error"] = str(exc)
            logger.error(message, data=log_data, exc_info=(type(exc), exc, exc.__traceback__))
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
