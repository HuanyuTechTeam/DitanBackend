"""认证相关功能模块"""

from datetime import datetime, timedelta
from typing import Any, Optional

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.models import Doctor
from app.schemas.doctor import TokenData

settings = get_settings()
security = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    """哈希密码"""
    password_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    password_bytes = plain_password.encode("utf-8")
    hashed_bytes = hashed_password.encode("utf-8")
    return bcrypt.checkpw(password_bytes, hashed_bytes)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """创建访问令牌"""
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta or timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(
        to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )


def decode_access_token(token: str) -> TokenData:
    """解码访问令牌"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无效的认证凭证",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload: dict[str, Any] = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        doctor_id = payload.get("doctor_id")
        username = payload.get("username")
        if not isinstance(doctor_id, int) or not isinstance(username, str):
            raise credentials_exception
        return TokenData(doctor_id=doctor_id, username=username)
    except JWTError:
        raise credentials_exception


async def get_current_doctor(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> Doctor:
    """获取当前登录的医生"""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证凭证",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_data = decode_access_token(credentials.credentials)
    result = await db.execute(
        select(Doctor).where(Doctor.doctor_id == token_data.doctor_id)
    )
    doctor = result.scalar_one_or_none()

    if doctor is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="医生账户不存在",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return doctor


async def get_current_active_doctor(
    current_doctor: Doctor = Depends(get_current_doctor),
) -> Doctor:
    """获取当前活跃的医生"""
    return current_doctor
