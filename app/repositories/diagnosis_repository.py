"""诊断记录数据访问层"""
from typing import Optional, Sequence
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import AIDiagnosisRecord, DoctorDiagnosisRecord
from app.repositories.base import BaseRepository


class AIDiagnosisRepository(BaseRepository[AIDiagnosisRecord]):
    """AI 诊断 Repository"""

    def __init__(self, db: AsyncSession):
        super().__init__(db, AIDiagnosisRecord)

    async def get_by_diagnosis_id(self, diagnosis_id: int) -> Optional[AIDiagnosisRecord]:
        """根据诊断ID获取"""
        return await self.get_by_id(diagnosis_id, "diagnosis_id")

    async def get_by_record_id(self, record_id: int) -> Sequence[AIDiagnosisRecord]:
        """获取就诊记录的所有 AI 诊断"""
        stmt = select(AIDiagnosisRecord).where(AIDiagnosisRecord.record_id == record_id)
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_by_diagnosis_and_record(
        self,
        diagnosis_id: int,
        record_id: int,
    ) -> Optional[AIDiagnosisRecord]:
        """根据诊断ID和记录ID获取"""
        stmt = select(AIDiagnosisRecord).where(
            AIDiagnosisRecord.diagnosis_id == diagnosis_id,
            AIDiagnosisRecord.record_id == record_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_ai_diagnosis(
        self,
        record_id: int,
        formatted_medical_record: Optional[str] = None,
        type_inference: Optional[str] = None,
        prescription: Optional[str] = None,
        exercise_prescription: Optional[str] = None,
        diagnosis_explanation: Optional[str] = None,
        response_time: Optional[float] = None,
        model_name: Optional[str] = None,
    ) -> AIDiagnosisRecord:
        """创建 AI 诊断记录"""
        ai_diagnosis = AIDiagnosisRecord(
            record_id=record_id,
            formatted_medical_record=formatted_medical_record,
            type_inference=type_inference,
            prescription=prescription,
            exercise_prescription=exercise_prescription,
            diagnosis_explanation=diagnosis_explanation,
            response_time=response_time,
            model_name=model_name,
        )
        return await self.create(ai_diagnosis)


class DoctorDiagnosisRepository(BaseRepository[DoctorDiagnosisRecord]):
    """医生诊断 Repository"""

    def __init__(self, db: AsyncSession):
        super().__init__(db, DoctorDiagnosisRecord)

    async def get_by_diagnosis_id(
        self,
        diagnosis_id: int,
        load_doctor: bool = False,
        load_medical_record: bool = False,
    ) -> Optional[DoctorDiagnosisRecord]:
        """根据诊断ID获取"""
        stmt = select(DoctorDiagnosisRecord).where(
            DoctorDiagnosisRecord.diagnosis_id == diagnosis_id
        )

        options = []
        if load_doctor:
            options.append(selectinload(DoctorDiagnosisRecord.doctor))
        if load_medical_record:
            options.append(selectinload(DoctorDiagnosisRecord.medical_record))

        if options:
            stmt = stmt.options(*options)

        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_record_id(
        self,
        record_id: int,
        load_doctor: bool = False,
    ) -> Sequence[DoctorDiagnosisRecord]:
        """获取就诊记录的所有医生诊断"""
        stmt = select(DoctorDiagnosisRecord).where(
            DoctorDiagnosisRecord.record_id == record_id
        )
        if load_doctor:
            stmt = stmt.options(selectinload(DoctorDiagnosisRecord.doctor))
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def create_doctor_diagnosis(
        self,
        record_id: int,
        doctor_id: int,
        formatted_medical_record: Optional[str] = None,
        type_inference: Optional[str] = None,
        treatment: Optional[str] = None,
        prescription: Optional[str] = None,
        exercise_prescription: Optional[str] = None,
        comments: Optional[str] = None,
    ) -> DoctorDiagnosisRecord:
        """创建医生诊断记录"""
        doctor_diagnosis = DoctorDiagnosisRecord(
            record_id=record_id,
            doctor_id=doctor_id,
            formatted_medical_record=formatted_medical_record,
            type_inference=type_inference,
            treatment=treatment,
            prescription=prescription,
            exercise_prescription=exercise_prescription,
            comments=comments,
        )
        return await self.create(doctor_diagnosis)

    async def update_fields(
        self,
        diagnosis: DoctorDiagnosisRecord,
        **fields,
    ) -> DoctorDiagnosisRecord:
        """更新诊断字段"""
        for field, value in fields.items():
            if value is not None:
                setattr(diagnosis, field, value)
        await self.db.flush()
        return diagnosis
