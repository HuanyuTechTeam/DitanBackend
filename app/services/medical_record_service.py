"""就诊记录业务逻辑层"""

from typing import Any
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

    def __init__(self, db: AsyncSession):
        self.db = db
        self.patient_repo = PatientRepository(db)
        self.record_repo = MedicalRecordRepository(db)
        self.pre_diagnosis_repo = PreDiagnosisRepository(db)
        self.sanzhen_repo = SanzhenRepository(db)
        self.ai_diagnosis_repo = AIDiagnosisRepository(db)
        self.doctor_diagnosis_repo = DoctorDiagnosisRepository(db)

    async def create_medical_record(
        self,
        record_data: MedicalRecordCreate,
    ) -> MedicalRecordResponse:
        """
        创建就诊记录（预就诊系统调用）

        Args:
            record_data: 就诊记录创建数据

        Returns:
            MedicalRecordResponse: 创建的就诊记录

        Raises:
            ValidationException: 患者不存在且未提供患者信息
            DuplicateException: UUID 已存在
        """
        # 获取或创建患者
        patient = await self.patient_repo.get_by_phone(record_data.patient_phone)

        if not patient:
            if not record_data.patient_info:
                raise ValidationException(
                    "患者不存在，请提供患者信息",
                    f"手机号 {record_data.patient_phone} 未注册",
                )
            patient = await self.patient_repo.create_patient(
                name=record_data.patient_info.name,
                sex=record_data.patient_info.sex,
                birthday=record_data.patient_info.birthday,
                phone=record_data.patient_info.phone,
            )

        # 检查 UUID 是否已存在
        existing_record = await self.record_repo.get_by_uuid(record_data.uuid)
        if existing_record:
            raise DuplicateException(f"就诊记录 UUID {record_data.uuid} 已存在")

        # 创建就诊记录
        medical_record = await self.record_repo.create_medical_record(
            patient_id=patient.patient_id,
            uuid=record_data.uuid,
            status="pending",
        )

        # 创建预诊记录
        pre_diagnosis = await self.pre_diagnosis_repo.create_pre_diagnosis(
            record_id=medical_record.record_id,
            uuid=record_data.pre_diagnosis.uuid,
            height=record_data.pre_diagnosis.height,
            weight=record_data.pre_diagnosis.weight,
            coze_conversation_log=record_data.pre_diagnosis.coze_conversation_log,
        )

        # 创建三诊分析结果
        if record_data.pre_diagnosis.sanzhen_analysis:
            sanzhen = record_data.pre_diagnosis.sanzhen_analysis
            await self.sanzhen_repo.create_sanzhen(
                pre_diagnosis_id=pre_diagnosis.pre_diagnosis_id,
                face=sanzhen.face,
                face_image_url=sanzhen.face_image_url,
                tongue_front=sanzhen.tongue_front,
                tongue_front_image_url=sanzhen.tongue_front_image_url,
                tongue_bottom=sanzhen.tongue_bottom,
                tongue_bottom_image_url=sanzhen.tongue_bottom_image_url,
                pulse=sanzhen.pulse,
                diagnosis_result=sanzhen.diagnosis_result,
            )

        # 提交并刷新
        await self.db.commit()
        await self.record_repo.refresh(medical_record, ["patient", "pre_diagnosis"])
        if medical_record.pre_diagnosis:
            await self.db.refresh(medical_record.pre_diagnosis, ["sanzhen_result"])

        return MedicalRecordResponse.model_validate(medical_record)

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
