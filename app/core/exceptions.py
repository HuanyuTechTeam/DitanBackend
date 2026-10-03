"""自定义异常模块"""

from typing import Any, Optional

from fastapi import status


class BaseAPIException(Exception):
    """基础 API 异常类"""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    default_message: str = "服务器内部错误"

    def __init__(self, message: Optional[str] = None, detail: Optional[Any] = None):
        self.message = message or self.default_message
        self.detail = detail
        super().__init__(self.message)


class ValidationException(BaseAPIException):
    """请求验证异常"""

    status_code = status.HTTP_400_BAD_REQUEST
    default_message = "请求参数验证失败"


class UnauthorizedException(BaseAPIException):
    """认证异常"""

    status_code = status.HTTP_401_UNAUTHORIZED
    default_message = "认证失败"


class ForbiddenException(BaseAPIException):
    """权限异常"""

    status_code = status.HTTP_403_FORBIDDEN
    default_message = "权限不足"


class NotFoundException(BaseAPIException):
    """资源未找到异常"""

    status_code = status.HTTP_404_NOT_FOUND
    default_message = "资源未找到"


class DuplicateException(BaseAPIException):
    """重复数据异常"""

    status_code = status.HTTP_409_CONFLICT
    default_message = "数据已存在"


class DatabaseException(BaseAPIException):
    """数据库异常"""

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    default_message = "数据库操作失败"


class ServiceException(BaseAPIException):
    """服务层异常"""

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    default_message = "服务处理失败"


class ConsultationError(BaseAPIException):
    """Consultation errors carry a stable code and optional recovery data."""

    def __init__(self, code: str, status_code: int = 409, **data: Any):
        self.code = code
        self.status_code = status_code
        self.data = {"code": code, **data}
        messages = {
            "VERSION_CONFLICT": "问诊状态已更新，请刷新后重试",
            "SESSION_BUSY": "已有进行中的问诊轮次",
            "TURN_ID_CONFLICT": "轮次编号对应了不同内容",
            "REPORT_NOT_READY": "当前不能生成报告",
            "CONSULTATION_CLOSED": "问诊已结束",
            "AUTH_EXPIRED": "问诊凭证已过期，请重新取票",
            "AUTH_TOKEN_INVALID": "问诊凭证无效",
            "AUTH_UNAVAILABLE": "问诊验票服务暂不可用",
            "NOT_FOUND": "问诊或轮次不存在",
            "INVALID_TURN": "当前不接受该轮次或回答内容无效",
        }
        super().__init__(messages.get(code, "问诊处理失败"))
