"""医生数据访问层"""
from typing import Optional
from datetime import datetime
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Doctor
from app.repositories.base import BaseRepository


class DoctorRepository(BaseRepository[Doctor]):
    """医生 Repository"""

    def __init__(self, db: AsyncSession):
        super().__init__(db, Doctor)

    async def get_by_doctor_id(self, doctor_id: int) -> Optional[Doctor]:
        """根据医生ID获取"""
        return await self.get_by_id(doctor_id, "doctor_id")

    async def get_by_username(self, username: str) -> Optional[Doctor]:
        """根据用户名获取"""
        stmt = select(Doctor).where(Doctor.username == username)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_phone(self, phone: str) -> Optional[Doctor]:
        """根据手机号获取"""
        stmt = select(Doctor).where(Doctor.phone == phone)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_username_or_phone(self, identifier: str) -> Optional[Doctor]:
        """根据用户名或手机号获取"""
        stmt = select(Doctor).where(
            or_(Doctor.username == identifier, Doctor.phone == identifier)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def check_phone_exists_for_other(
        self,
        phone: str,
        exclude_doctor_id: int,
    ) -> bool:
        """检查手机号是否被其他医生使用"""
        stmt = select(Doctor).where(
            Doctor.phone == phone,
            Doctor.doctor_id != exclude_doctor_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def create_doctor(
        self,
        username: str,
        password_hash: str,
        name: str,
        gender: str,
        phone: str,
        department: Optional[str] = None,
        position: Optional[str] = None,
        bio: Optional[str] = None,
    ) -> Doctor:
        """创建新医生"""
        doctor = Doctor(
            username=username,
            password_hash=password_hash,
            name=name,
            gender=gender,
            phone=phone,
            department=department,
            position=position,
            bio=bio,
        )
        return await self.create(doctor)

    async def update_last_login(self, doctor: Doctor) -> Doctor:
        """更新最后登录时间"""
        doctor.last_login = datetime.utcnow()
        await self.db.flush()
        return doctor

    async def update_password(self, doctor: Doctor, password_hash: str) -> Doctor:
        """更新密码"""
        doctor.password_hash = password_hash
        doctor.updated_at = datetime.utcnow()
        await self.db.flush()
        return doctor

    async def update_info(self, doctor: Doctor, **fields) -> Doctor:
        """更新医生信息"""
        for field, value in fields.items():
            if hasattr(doctor, field):
                setattr(doctor, field, value)
        doctor.updated_at = datetime.utcnow()
        await self.db.flush()
        return doctor
