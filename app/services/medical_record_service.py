"""就诊记录业务逻辑层"""

import hashlib
import json
from typing import Any
from sqlalchemy.exc import IntegrityError
from app.core.organization import OrganizationContext
from app.core.upload_auth import UploadPrincipal
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    NotFoundException,
    ValidationException,
    DuplicateException,
)
from app.models import PatientMedicalRecord, DiagnosisType
from app.repositories import (
    PatientRepository,
    MedicalRecordRepository,
    PreDiagnosisRepository,
    SanzhenRepository,
    AIDiagnosisRepository,
    DoctorDiagnosisRepository,
)
from app.schemas.patient import (
    PatientResponse,
    MedicalRecordCreate,
    MedicalRecordResponse,
    PreDiagnosisResponse,
    AIDiagnosisResponse,
    DoctorDiagnosisResponse,
)
from app.schemas.common import DiagnosisType as SchemaDiagnosisType


class MedicalRecordService:
    """就诊记录服务类"""

    def __init__(self, db: AsyncSession, organization: OrganizationContext):
        self.db = db
        self.organization = organization
        self.upload_replayed = False
        self.upload_record_id: int | None = None
        self.patient_repo = PatientRepository(db, organization)
        self.record_repo = MedicalRecordRepository(db, organization)
        self.pre_diagnosis_repo = PreDiagnosisRepository(db, organization)
        self.sanzhen_repo = SanzhenRepository(db, organization)
        self.ai_diagnosis_repo = AIDiagnosisRepository(db, organization)
        self.doctor_diagnosis_repo = DoctorDiagnosisRepository(db, organization)

    async def create_medical_record(
        self,
        record_data: MedicalRecordCreate,
        principal: UploadPrincipal,
        request_id: str,
    ) -> MedicalRecordResponse:
        """Atomic upload, with database-enforced idempotency and bounded race recovery."""
        if principal.organization != self.organization:
            raise NotFoundException()
        digest = hashlib.sha256(
            json.dumps(
                record_data.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        try:
            for attempt in range(3):
                existing = await self.record_repo.get_by_uuid(record_data.uuid)
                if existing is not None:
                    return await self._replay(existing, digest)
                try:
                    record = await self._insert_upload(
                        record_data, principal, request_id, digest
                    )
                    # Serialize before commit so even response validation failure rolls back all rows.
                    response = await self._upload_response(record.record_id)
                    await self.db.commit()
                    self.upload_record_id = response.record_id
                    return response
                except IntegrityError:
                    await self.db.rollback()
                    # The winning transaction is now visible at READ COMMITTED.
                    existing = await self.record_repo.get_by_uuid(record_data.uuid)
                    if existing is not None:
                        return await self._replay(existing, digest)
                    duplicate_pre = await self.pre_diagnosis_repo.get_by_id(
                        record_data.pre_diagnosis.uuid, "uuid"
                    )
                    if duplicate_pre is not None or attempt == 2:
                        raise DuplicateException("上传内容与已有记录冲突") from None
        except BaseException:
            await self.db.rollback()
            raise
        raise RuntimeError("Upload retry loop exhausted")

    async def _replay(
        self, record: PatientMedicalRecord, digest: str
    ) -> MedicalRecordResponse:
        self.upload_record_id = record.record_id
        if record.upload_digest is None or record.upload_digest != digest:
            raise DuplicateException("相同病例 UUID 的上传内容冲突")
        self.upload_replayed = True
        return await self._upload_response(record.record_id)

    async def _upload_response(self, record_id: int) -> MedicalRecordResponse:
        record = await self.record_repo.get_by_record_id(
            record_id,
            load_patient=True,
            load_pre_diagnosis=True,
        )
        return MedicalRecordResponse.model_validate(record)

    async def _insert_upload(
        self,
        data: MedicalRecordCreate,
        principal: UploadPrincipal,
        request_id: str,
        digest: str,
    ) -> PatientMedicalRecord:
        patient = await self.patient_repo.get_by_phone(data.patient_phone)
        if patient is None:
            if data.patient_info is None:
                raise ValidationException("患者不存在，请提供患者信息")
            patient = await self.patient_repo.create_patient(
                name=data.patient_info.name,
                sex=data.patient_info.sex,
                birthday=data.patient_info.birthday,
                phone=data.patient_phone,
            )
        record = await self.record_repo.create_medical_record(
            patient_id=patient.patient_id,
            uuid=data.uuid,
        )
        record.upload_digest = digest
        record.upload_user_id = principal.user_id
        record.upload_device_id = principal.device_id
        record.upload_client_session_id = principal.client_session_id
        record.upload_request_id = request_id
        pre = await self.pre_diagnosis_repo.create_pre_diagnosis(
            record_id=record.record_id,
            uuid=data.pre_diagnosis.uuid,
            height=data.pre_diagnosis.height,
            weight=data.pre_diagnosis.weight,
            coze_conversation_log=data.pre_diagnosis.coze_conversation_log,
        )
        if data.pre_diagnosis.sanzhen_analysis is not None:
            await self.sanzhen_repo.create_sanzhen(
                pre_diagnosis_id=pre.pre_diagnosis_id,
                **data.pre_diagnosis.sanzhen_analysis.model_dump(),
            )
        await self.db.flush()
        return record

    async def get_complete_record(self, record_id: int) -> dict[str, Any]:
        """
        获取完整的就诊记录信息

        Args:
            record_id: 就诊记录ID

        Returns:
            dict: 包含就诊记录、患者、预诊、诊断等完整信息

        Raises:
            NotFoundException: 就诊记录不存在
        """
        medical_record = await self.record_repo.get_by_record_id(
            record_id,
            load_patient=True,
            load_pre_diagnosis=True,
        )

        if not medical_record:
            raise NotFoundException(f"未找到就诊记录 ID: {record_id}")

        # 分别查询诊断记录
        ai_diagnoses = await self.ai_diagnosis_repo.get_by_record_id(record_id)
        doctor_diagnoses = await self.doctor_diagnosis_repo.get_by_record_id(
            record_id, load_doctor=True
        )

        # 构建诊断列表
        diagnoses_list = []
        for ai_diagnosis in ai_diagnoses:
            diagnoses_list.append(
                AIDiagnosisResponse.model_validate(ai_diagnosis).model_dump()
            )
        for doctor_diagnosis in doctor_diagnoses:
            diagnoses_list.append(
                DoctorDiagnosisResponse(
                    diagnosis_id=doctor_diagnosis.diagnosis_id,
                    record_id=doctor_diagnosis.record_id,
                    type=SchemaDiagnosisType(doctor_diagnosis.type.value),
                    doctor_id=doctor_diagnosis.doctor_id,
                    doctor_name=(
                        doctor_diagnosis.doctor.name
                        if doctor_diagnosis.doctor
                        else None
                    ),
                    formatted_medical_record=doctor_diagnosis.formatted_medical_record,
                    type_inference=doctor_diagnosis.type_inference,
                    treatment=doctor_diagnosis.treatment,
                    prescription=doctor_diagnosis.prescription,
                    exercise_prescription=doctor_diagnosis.exercise_prescription,
                    comments=doctor_diagnosis.comments,
                    created_at=doctor_diagnosis.created_at,
                    updated_at=doctor_diagnosis.updated_at,
                ).model_dump()
            )

        # 按创建时间排序
        diagnoses_list.sort(key=lambda x: x["created_at"])

        return {
            "record_id": medical_record.record_id,
            "uuid": medical_record.uuid,
            "status": medical_record.status,
            "created_at": medical_record.created_at.isoformat(),
            "updated_at": medical_record.updated_at.isoformat(),
            "patient": PatientResponse.model_validate(
                medical_record.patient
            ).model_dump(),
            "pre_diagnosis": (
                PreDiagnosisResponse.model_validate(
                    medical_record.pre_diagnosis
                ).model_dump()
                if medical_record.pre_diagnosis
                else None
            ),
            "diagnoses": diagnoses_list,
        }

    async def get_record_with_pre_diagnosis(
        self,
        record_id: int,
    ) -> PatientMedicalRecord:
        """
        获取就诊记录（包含预诊信息）

        Args:
            record_id: 就诊记录ID

        Returns:
            PatientMedicalRecord: 就诊记录

        Raises:
            NotFoundException: 就诊记录不存在
        """
        record = await self.record_repo.get_by_record_id(
            record_id, load_pre_diagnosis=True
        )
        if not record:
            raise NotFoundException(f"未找到就诊记录 ID: {record_id}")
        return record

    async def confirm_record(
        self,
        record_id: int,
        doctor_name: str,
    ) -> dict[str, Any]:
        """
        确认就诊完成

        Args:
            record_id: 就诊记录ID
            doctor_name: 确认医生姓名

        Returns:
            dict: 确认结果

        Raises:
            NotFoundException: 就诊记录不存在
            ValidationException: 状态不允许确认
        """
        medical_record = await self.record_repo.get_by_record_id(
            record_id, load_diagnoses=True
        )

        if not medical_record:
            raise NotFoundException(f"未找到就诊记录 ID: {record_id}")

        if medical_record.status == "confirmed":
            raise ValidationException(
                "就诊记录已确认",
                "此就诊记录已经确认完成，无需重复确认",
            )

        has_doctor_diagnosis = any(
            d.type == DiagnosisType.DOCTOR_DIAGNOSIS for d in medical_record.diagnoses
        )
        if not has_doctor_diagnosis:
            raise ValidationException("无法确认就诊", "请先创建医生诊断记录后再确认")

        await self.record_repo.update_status(medical_record, "confirmed")
        await self.db.commit()
        await self.record_repo.refresh(medical_record)

        return {
            "record_id": medical_record.record_id,
            "status": medical_record.status,
            "confirmed_by": doctor_name,
            "confirmed_at": medical_record.updated_at.isoformat(),
        }
