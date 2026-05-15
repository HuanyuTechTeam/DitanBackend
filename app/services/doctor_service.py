"""医生业务逻辑层"""

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import hash_password, verify_password, create_access_token
from app.core.exceptions import ValidationException, DuplicateException
from app.models import Doctor
from app.repositories import DoctorRepository
from app.schemas.doctor import (
    DoctorRegister,
    DoctorLogin,
    DoctorResponse,
    DoctorUpdate,
    PasswordChange,
    LoginResponse,
)


class DoctorService:
    """医生服务类"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.doctor_repo = DoctorRepository(db)

    async def register(self, doctor_data: DoctorRegister) -> DoctorResponse:
        """
        医生注册

        Args:
            doctor_data: 注册数据

        Returns:
            DoctorResponse: 注册成功的医生信息

        Raises:
            DuplicateException: 用户名或手机号已存在
        """
        # 检查用户名是否已存在
        existing = await self.doctor_repo.get_by_username(doctor_data.username)
        if existing:
            raise DuplicateException(f"用户名 {doctor_data.username} 已被注册")

        # 检查手机号是否已存在
        existing = await self.doctor_repo.get_by_phone(doctor_data.phone)
        if existing:
            raise DuplicateException(f"手机号 {doctor_data.phone} 已被注册")

        # 创建医生
        doctor = await self.doctor_repo.create_doctor(
            username=doctor_data.username,
            password_hash=hash_password(doctor_data.password),
            name=doctor_data.name,
            gender=doctor_data.gender,
            phone=doctor_data.phone,
            department=doctor_data.department,
            position=doctor_data.position,
            bio=doctor_data.bio,
        )

        await self.db.commit()
        await self.doctor_repo.refresh(doctor)

        return DoctorResponse.model_validate(doctor)

    async def login(self, login_data: DoctorLogin) -> LoginResponse:
        """
        医生登录

        Args:
            login_data: 登录数据

        Returns:
            LoginResponse: 登录成功响应（包含 token）

        Raises:
            HTTPException: 认证失败
        """
        doctor = await self.doctor_repo.get_by_username_or_phone(login_data.username)

        if not doctor or not verify_password(login_data.password, doctor.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户名/手机号或密码错误",
            )

        # 更新最后登录时间
        await self.doctor_repo.update_last_login(doctor)
        await self.db.commit()
        await self.doctor_repo.refresh(doctor)

        # 生成 token
        access_token = create_access_token(
            data={"doctor_id": doctor.doctor_id, "username": doctor.username}
        )

        return LoginResponse(
            access_token=access_token,
            token_type="bearer",
            doctor=DoctorResponse.model_validate(doctor),
        )

    async def get_doctor_info(self, doctor: Doctor) -> DoctorResponse:
        """
        获取医生信息

        Args:
            doctor: 医生实体

        Returns:
            DoctorResponse: 医生信息
        """
        return DoctorResponse.model_validate(doctor)

    async def update_doctor_info(
        self,
        doctor: Doctor,
        update_data: DoctorUpdate,
    ) -> DoctorResponse:
        """
        更新医生信息

        Args:
            doctor: 医生实体
            update_data: 更新数据

        Returns:
            DoctorResponse: 更新后的医生信息

        Raises:
            DuplicateException: 手机号已被其他医生使用
        """
        # 检查手机号是否被其他医生使用
        if update_data.phone and update_data.phone != doctor.phone:
            exists = await self.doctor_repo.check_phone_exists_for_other(
                update_data.phone, doctor.doctor_id
            )
            if exists:
                raise DuplicateException(f"手机号 {update_data.phone} 已被其他医生使用")

        # 更新信息
        update_fields = update_data.model_dump(exclude_unset=True)
        await self.doctor_repo.update_info(doctor, **update_fields)
        await self.db.commit()
        await self.doctor_repo.refresh(doctor)

        return DoctorResponse.model_validate(doctor)

    async def change_password(
        self,
        doctor: Doctor,
        password_data: PasswordChange,
    ) -> None:
        """
        修改密码

        Args:
            doctor: 医生实体
            password_data: 密码数据

        Raises:
            ValidationException: 旧密码不正确
        """
        if not verify_password(password_data.old_password, doctor.password_hash):
            raise ValidationException("旧密码不正确")

        await self.doctor_repo.update_password(
            doctor, hash_password(password_data.new_password)
        )
        await self.db.commit()
