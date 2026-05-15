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
