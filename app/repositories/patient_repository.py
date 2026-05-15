"""患者数据访问层"""

from datetime import date
from typing import Optional, Sequence
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Patient, PatientMedicalRecord
from app.repositories.base import BaseRepository


class PatientRepository(BaseRepository[Patient]):
    """患者 Repository"""

    def __init__(self, db: AsyncSession):
        super().__init__(db, Patient)

    async def get_by_phone(self, phone: str) -> Optional[Patient]:
        """根据手机号查询患者"""
        stmt = select(Patient).where(Patient.phone == phone)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_patient_id(self, patient_id: int) -> Optional[Patient]:
        """根据患者ID查询"""
        return await self.get_by_id(patient_id, "patient_id")

    async def create_patient(
        self,
        name: str,
        sex: str,
        birthday: date,
        phone: str,
    ) -> Patient:
        """创建新患者"""
        patient = Patient(
            name=name,
            sex=sex,
            birthday=birthday,
            phone=phone,
        )
        return await self.create(patient)

    async def get_medical_records_by_patient(
        self,
        patient_id: int,
        order_desc: bool = True,
    ) -> Sequence[PatientMedicalRecord]:
        """获取患者的所有就诊记录"""
        stmt = select(PatientMedicalRecord).where(
            PatientMedicalRecord.patient_id == patient_id
        )
        if order_desc:
            stmt = stmt.order_by(PatientMedicalRecord.created_at.desc())
        else:
            stmt = stmt.order_by(PatientMedicalRecord.created_at.asc())
        result = await self.db.execute(stmt)
        return result.scalars().all()
