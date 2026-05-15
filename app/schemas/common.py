"""公共 Schema 定义"""

import re
from enum import Enum
from typing import Optional, Any

from pydantic import BaseModel, Field


class Gender(str, Enum):
    """性别枚举（用于 API 序列化）"""

    MALE = "MALE"
    FEMALE = "FEMALE"
    OTHER = "OTHER"


class DiagnosisType(str, Enum):
    """诊断类型枚举（用于 API 序列化）"""

    AI_DIAGNOSIS = "AI_DIAGNOSIS"
    DOCTOR_DIAGNOSIS = "DOCTOR_DIAGNOSIS"


class PhoneValidatorMixin:
    """手机号验证混入类"""

    @staticmethod
    def validate_phone_format(v: str) -> str:
        if not re.match(r"^1[3-9]\d{9}$", v):
            raise ValueError("手机号格式不正确")
        return v


class UUIDValidatorMixin:
    """UUID 验证混入类"""

    @staticmethod
    def validate_uuid_format(v: str) -> str:
        uuid_pattern = re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            re.IGNORECASE,
        )
        if not uuid_pattern.match(v):
            raise ValueError("UUID 格式不正确")
        return v


class APIResponse(BaseModel):
    """通用 API 响应模型"""

    success: bool = Field(..., description="请求是否成功")
    message: str = Field(..., description="响应消息")
    data: Optional[Any] = Field(None, description="响应数据")


class ErrorResponse(BaseModel):
    """错误响应模型"""

    success: bool = Field(default=False, description="请求是否成功")
    message: str = Field(..., description="错误消息")
    detail: Optional[str] = Field(None, description="错误详情")
