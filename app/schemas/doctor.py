"""医生用户相关 Pydantic 模型"""

import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import Gender, PhoneValidatorMixin


class DoctorRegister(BaseModel, PhoneValidatorMixin):
    """医生注册请求"""

    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    password: str = Field(..., min_length=6, max_length=50, description="密码")
    name: str = Field(..., min_length=2, max_length=50, description="医生姓名")
    gender: Gender = Field(..., description="性别")
    phone: str = Field(..., description="手机号")
    department: Optional[str] = Field(None, max_length=100, description="科室")
    position: Optional[str] = Field(None, max_length=100, description="职位")
    bio: Optional[str] = Field(None, description="个人简介")

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_]+$", v):
            raise ValueError("用户名只能包含字母、数字和下划线")
        return v

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return cls.validate_phone_format(v)


class DoctorLogin(BaseModel):
    """医生登录请求"""

    username: str = Field(..., description="用户名或手机号")
    password: str = Field(..., description="密码")


class DoctorResponse(BaseModel):
    """医生信息响应"""

    doctor_id: int
    username: str
    name: str
    gender: Gender
    phone: str
    department: Optional[str] = None
    position: Optional[str] = None
    bio: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    last_login: Optional[datetime] = None

    model_config = {"from_attributes": True}


class LoginResponse(BaseModel):
    """登录响应"""

    access_token: str = Field(..., description="访问令牌")
    token_type: str = Field(default="bearer", description="令牌类型")
    doctor: DoctorResponse = Field(..., description="医生信息")


class DoctorUpdate(BaseModel, PhoneValidatorMixin):
    """医生信息更新请求"""

    name: Optional[str] = Field(
        None, min_length=2, max_length=50, description="医生姓名"
    )
    gender: Optional[Gender] = Field(None, description="性别")
    phone: Optional[str] = Field(None, description="手机号")
    department: Optional[str] = Field(None, max_length=100, description="科室")
    position: Optional[str] = Field(None, max_length=100, description="职位")
    bio: Optional[str] = Field(None, description="个人简介")

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return cls.validate_phone_format(v)
        return v


class PasswordChange(BaseModel):
    """修改密码请求"""

    old_password: str = Field(..., description="旧密码")
    new_password: str = Field(..., min_length=6, max_length=50, description="新密码")


class TokenData(BaseModel):
    """Token载荷数据"""

    doctor_id: int
    username: str
