"""患者业务逻辑层"""

from datetime import date
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.organization import OrganizationContext
from app.core.exceptions import NotFoundException, ValidationException
from app.models import Patient
from app.repositories import PatientRepository, MedicalRecordRepository
from app.schemas.patient import (
    PatientResponse,
    PatientQueryResponse,
    MedicalRecordListItem,
)


class PatientService:
    """患者服务类"""

    def __init__(self, db: AsyncSession, organization: OrganizationContext):
        self.db = db
        self.patient_repo = PatientRepository(db, organization)
        self.record_repo = MedicalRecordRepository(db, organization)

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
            raise NotFoundException("未找到患者")

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
        birthday: Optional[date] = None,
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

        if name is None or sex is None or birthday is None:
            raise ValidationException(
                "患者不存在，请提供患者信息",
                "当前组织未注册该患者",
            )

        patient = await self.patient_repo.create_patient(
            name=name,
            sex=sex,
            birthday=birthday,
            phone=phone,
        )
        return patient
