"""认证相关功能模块"""

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import secrets
from typing import Any, Optional

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.models import Doctor, Gender
from app.schemas.doctor import TokenData

settings = get_settings()
security = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class ApkioOrgTokenData:
    """Apkio Org 用户 Token 载荷。"""

    user_id: str
    org_id: str
    email: str
    display_name: Optional[str]
    roles: list[str]
    permission_scopes: dict[str, str]


def _credentials_exception(detail: str = "无效的认证凭证") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


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


def _decode_local_access_token(token: str) -> Optional[TokenData]:
    """尝试解码 Ditan 本地医生访问令牌。"""
    try:
        payload: dict[str, Any] = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        doctor_id = payload.get("doctor_id")
        username = payload.get("username")
        if not isinstance(doctor_id, int) or not isinstance(username, str):
            return None
        return TokenData(doctor_id=doctor_id, username=username)
    except JWTError:
        return None


def decode_access_token(token: str) -> TokenData:
    """解码 Ditan 本地访问令牌。"""
    token_data = _decode_local_access_token(token)
    if token_data is None:
        raise _credentials_exception()
    return token_data


def _normalize_apkio_permissions(value: Any) -> dict[str, str]:
    """兼容 Apkio Org token 的权限字典和可能的权限列表。"""
    if isinstance(value, dict):
        return {str(key): str(scope) for key, scope in value.items()}
    if isinstance(value, list):
        return {str(permission): "" for permission in value}
    return {}


def decode_apkio_org_token(token: str) -> ApkioOrgTokenData:
    """解码并校验 Apkio Org 用户访问令牌。"""
    if not settings.APKIO_JWT_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Apkio 认证未配置",
        )

    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.APKIO_JWT_SECRET_KEY,
            algorithms=[settings.APKIO_JWT_ALGORITHM],
            audience=settings.APKIO_ORG_TOKEN_AUDIENCE,
        )
    except JWTError:
        raise _credentials_exception()

    user_id = payload.get("sub")
    org_id = payload.get("orgId")
    email = payload.get("email")
    display_name = payload.get("displayName")
    if not isinstance(user_id, str) or not user_id:
        raise _credentials_exception()
    if not isinstance(org_id, str) or not org_id:
        raise _credentials_exception()
    if not isinstance(email, str) or not email:
        raise _credentials_exception()
    if display_name is not None and not isinstance(display_name, str):
        display_name = None

    permission_scopes = _normalize_apkio_permissions(payload.get("permissions", {}))
    required_permission = settings.APKIO_REQUIRED_PERMISSION.strip()
    if required_permission and required_permission not in permission_scopes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="缺少 Ditan 访问权限",
        )

    roles_claim = payload.get("roles", [])
    roles = [str(role) for role in roles_claim] if isinstance(roles_claim, list) else []
    return ApkioOrgTokenData(
        user_id=user_id,
        org_id=org_id,
        email=email,
        display_name=display_name,
        roles=roles,
        permission_scopes=permission_scopes,
    )


def _apkio_doctor_name(token_data: ApkioOrgTokenData) -> str:
    """从 Apkio 身份生成 Ditan 医生初始姓名。"""
    name = (token_data.display_name or token_data.email.split("@", 1)[0]).strip()
    if not name:
        name = "Apkio医生"
    if len(name) < 2:
        name = f"{name}医生"
    return name[:50]


async def _generate_apkio_username(
    db: AsyncSession, token_data: ApkioOrgTokenData
) -> str:
    """生成稳定且不冲突的 Ditan 用户名。"""
    user_id_part = "".join(ch for ch in token_data.user_id if ch.isalnum())[:24]
    base_username = f"apkio_{user_id_part or 'doctor'}"[:50]

    for index in range(100):
        suffix = "" if index == 0 else f"_{index}"
        username = f"{base_username[: 50 - len(suffix)]}{suffix}"
        existing = await db.scalar(
            select(Doctor.doctor_id).where(Doctor.username == username)
        )
        if existing is None:
            return username

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="无法生成 Apkio 医生用户名",
    )


async def _generate_apkio_placeholder_phone(
    db: AsyncSession, token_data: ApkioOrgTokenData
) -> str:
    """生成满足现有 Doctor 非空唯一约束的占位手机号。"""
    digest = hashlib.sha256(
        f"{token_data.org_id}:{token_data.user_id}".encode("utf-8")
    ).hexdigest()
    base_number = int(digest[:12], 16) % 1_000_000_000

    for offset in range(1000):
        phone = f"19{(base_number + offset) % 1_000_000_000:09d}"
        existing = await db.scalar(select(Doctor.doctor_id).where(Doctor.phone == phone))
        if existing is None:
            return phone

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="无法生成 Apkio 医生占位手机号",
    )


async def get_or_create_apkio_doctor(
    db: AsyncSession, token_data: ApkioOrgTokenData
) -> Doctor:
    """根据 Apkio 身份获取或自动创建本地医生业务实体。"""
    result = await db.execute(
        select(Doctor).where(
            Doctor.apkio_org_id == token_data.org_id,
            Doctor.apkio_user_id == token_data.user_id,
        )
    )
    doctor = result.scalar_one_or_none()
    if doctor is not None:
        return doctor

    if not settings.APKIO_AUTO_CREATE_DOCTOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apkio 账号未绑定医生身份",
        )

    doctor = Doctor(
        username=await _generate_apkio_username(db, token_data),
        password_hash=hash_password(secrets.token_urlsafe(32)),
        name=_apkio_doctor_name(token_data),
        gender=Gender.OTHER,
        phone=await _generate_apkio_placeholder_phone(db, token_data),
        department=None,
        position=None,
        bio=None,
        apkio_org_id=token_data.org_id,
        apkio_user_id=token_data.user_id,
        apkio_email=token_data.email,
    )
    db.add(doctor)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        result = await db.execute(
            select(Doctor).where(
                Doctor.apkio_org_id == token_data.org_id,
                Doctor.apkio_user_id == token_data.user_id,
            )
        )
        doctor = result.scalar_one_or_none()
        if doctor is not None:
            return doctor
        raise

    await db.refresh(doctor)
    return doctor


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

    token = credentials.credentials
    token_data = _decode_local_access_token(token)
    if token_data is not None:
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

    if settings.APKIO_AUTH_ENABLED:
        apkio_token_data = decode_apkio_org_token(token)
        return await get_or_create_apkio_doctor(db, apkio_token_data)

    raise _credentials_exception()


async def get_current_active_doctor(
    current_doctor: Doctor = Depends(get_current_doctor),
) -> Doctor:
    """获取当前活跃的医生"""
    return current_doctor
