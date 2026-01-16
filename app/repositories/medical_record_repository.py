"""就诊记录数据访问层"""
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    PatientMedicalRecord,
    PreDiagnosisRecord,
    SanzhenAnalysisResult,
)
from app.repositories.base import BaseRepository


class MedicalRecordRepository(BaseRepository[PatientMedicalRecord]):
    """就诊记录 Repository"""

    def __init__(self, db: AsyncSession):
        super().__init__(db, PatientMedicalRecord)

    async def get_by_record_id(
        self,
        record_id: int,
        load_patient: bool = False,
        load_pre_diagnosis: bool = False,
        load_diagnoses: bool = False,
    ) -> Optional[PatientMedicalRecord]:
        """根据记录ID获取就诊记录（支持关联加载）"""
        stmt = select(PatientMedicalRecord).where(
            PatientMedicalRecord.record_id == record_id
        )

        options = []
        if load_patient:
            options.append(selectinload(PatientMedicalRecord.patient))
        if load_pre_diagnosis:
            options.append(
                selectinload(PatientMedicalRecord.pre_diagnosis).selectinload(
                    PreDiagnosisRecord.sanzhen_result
                )
            )
        if load_diagnoses:
            options.append(selectinload(PatientMedicalRecord.diagnoses))

        if options:
            stmt = stmt.options(*options)

        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_uuid(self, uuid: str) -> Optional[PatientMedicalRecord]:
        """根据 UUID 获取就诊记录"""
        stmt = select(PatientMedicalRecord).where(PatientMedicalRecord.uuid == uuid)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_medical_record(
        self,
        patient_id: int,
        uuid: str,
        status: str = "pending",
    ) -> PatientMedicalRecord:
        """创建就诊记录"""
        record = PatientMedicalRecord(
            patient_id=patient_id,
            uuid=uuid,
            status=status,
        )
        return await self.create(record)

    async def update_status(
        self,
        record: PatientMedicalRecord,
        status: str,
    ) -> PatientMedicalRecord:
        """更新就诊记录状态"""
        record.status = status
        await self.db.flush()
        return record


class PreDiagnosisRepository(BaseRepository[PreDiagnosisRecord]):
    """预诊记录 Repository"""

    def __init__(self, db: AsyncSession):
        super().__init__(db, PreDiagnosisRecord)

    async def create_pre_diagnosis(
        self,
        record_id: int,
        uuid: str,
        height: Optional[float] = None,
        weight: Optional[float] = None,
        coze_conversation_log: Optional[str] = None,
    ) -> PreDiagnosisRecord:
        """创建预诊记录"""
        pre_diagnosis = PreDiagnosisRecord(
            record_id=record_id,
            uuid=uuid,
            height=height,
            weight=weight,
            coze_conversation_log=coze_conversation_log,
        )
        return await self.create(pre_diagnosis)


class SanzhenRepository(BaseRepository[SanzhenAnalysisResult]):
    """三诊分析结果 Repository"""

    def __init__(self, db: AsyncSession):
        super().__init__(db, SanzhenAnalysisResult)

    async def create_sanzhen(
        self,
        pre_diagnosis_id: int,
        face: Optional[str] = None,
        face_image_url: Optional[str] = None,
        tongue_front: Optional[str] = None,
        tongue_front_image_url: Optional[str] = None,
        tongue_bottom: Optional[str] = None,
        tongue_bottom_image_url: Optional[str] = None,
        pulse: Optional[str] = None,
        diagnosis_result: Optional[str] = None,
    ) -> SanzhenAnalysisResult:
        """创建三诊分析结果"""
        sanzhen = SanzhenAnalysisResult(
            pre_diagnosis_id=pre_diagnosis_id,
            face=face,
            face_image_url=face_image_url,
            tongue_front=tongue_front,
            tongue_front_image_url=tongue_front_image_url,
            tongue_bottom=tongue_bottom,
            tongue_bottom_image_url=tongue_bottom_image_url,
            pulse=pulse,
            diagnosis_result=diagnosis_result,
        )
        return await self.create(sanzhen)
