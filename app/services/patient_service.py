"""患者业务逻辑层"""
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException, ValidationException
from app.models import Patient, PatientMedicalRecord
from app.repositories import PatientRepository, MedicalRecordRepository
from app.schemas.patient import (
    PatientResponse,
    PatientQueryResponse,
    MedicalRecordListItem,
)


class PatientService:
    """患者服务类"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.patient_repo = PatientRepository(db)
        self.record_repo = MedicalRecordRepository(db)

    async def query_by_phone(self, phone: str) -> PatientQueryResponse:
        """
        通过手机号查询患者信息和历史就诊记录

        Args:
            phone: 患者手机号

        Returns:
            PatientQueryResponse: 包含患者信息和就诊记录列表

        Raises:
            NotFoundException: 患者不存在
        """
        patient = await self.patient_repo.get_by_phone(phone)
        if not patient:
            raise NotFoundException(f"未找到手机号为 {phone} 的患者")

        medical_records = await self.patient_repo.get_medical_records_by_patient(
            patient.patient_id
        )

        records_list = [
            MedicalRecordListItem(
                record_id=record.record_id,
                uuid=record.uuid,
                status=record.status,
                created_at=record.created_at,
                patient_name=patient.name,
                patient_phone=patient.phone,
            )
            for record in medical_records
        ]

        return PatientQueryResponse(
            patient=PatientResponse.model_validate(patient),
            medical_records=records_list,
        )

    async def get_or_create_patient(
        self,
        phone: str,
        name: Optional[str] = None,
        sex: Optional[str] = None,
        birthday: Optional[str] = None,
    ) -> Patient:
        """
        获取或创建患者

        Args:
            phone: 手机号
            name: 姓名（创建新患者时必需）
            sex: 性别（创建新患者时必需）
            birthday: 生日（创建新患者时必需）

        Returns:
            Patient: 患者实体

        Raises:
            ValidationException: 患者不存在且未提供必要信息
        """
        patient = await self.patient_repo.get_by_phone(phone)

        if patient:
            return patient

        if not all([name, sex, birthday]):
            raise ValidationException(
                "患者不存在，请提供患者信息",
                f"手机号 {phone} 未注册",
            )

        patient = await self.patient_repo.create_patient(
            name=name,
            sex=sex,
            birthday=birthday,
            phone=phone,
        )
        return patient
