"""诊断业务逻辑层"""

from typing import Optional, Any, Callable
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import get_settings
from app.core.organization import OrganizationContext
from app.core.exceptions import (
    NotFoundException,
    ValidationException,
    DatabaseException,
)
from app.models import Doctor, AIDiagnosisRecord
from app.repositories import (
    MedicalRecordRepository,
    AIDiagnosisRepository,
    DoctorDiagnosisRepository,
)
from app.schemas.common import DiagnosisType as SchemaDiagnosisType
from app.schemas.patient import (
    AIDiagnosisCreate,
    AIDiagnosisResponse,
    DoctorDiagnosisCreate,
    DoctorDiagnosisUpdate,
    DoctorDiagnosisResponse,
)
from app.services.tcm_diagnosis_service import TCMDiagnosisService

settings = get_settings()


def get_tcm_service() -> TCMDiagnosisService:
    """获取中医诊断服务实例"""
    return TCMDiagnosisService(
        api_key=settings.AI_API_KEY,
        base_url=settings.AI_BASE_URL,
        model_name=settings.AI_MODEL_NAME,
    )


class DiagnosisService:
    """诊断服务类"""

    def __init__(self, db: AsyncSession, organization: OrganizationContext):
        self.db = db
        self.record_repo = MedicalRecordRepository(db, organization)
        self.ai_diagnosis_repo = AIDiagnosisRepository(db, organization)
        self.doctor_diagnosis_repo = DoctorDiagnosisRepository(db, organization)

    async def create_ai_diagnosis(
        self,
        record_id: int,
        diagnosis_data: AIDiagnosisCreate,
        tcm_service: Optional[TCMDiagnosisService] = None,
        tcm_service_factory: Optional[Callable[[], TCMDiagnosisService]] = None,
    ) -> AIDiagnosisResponse:
        """
        生成 AI 诊断

        Args:
            record_id: 就诊记录ID
            diagnosis_data: 诊断输入数据

        Returns:
            AIDiagnosisResponse: AI 诊断结果

        Raises:
            NotFoundException: 就诊记录不存在
            DatabaseException: AI 诊断失败
        """
        medical_record = await self.record_repo.get_by_record_id(
            record_id, load_pre_diagnosis=True
        )
        if not medical_record:
            raise NotFoundException(f"未找到就诊记录 ID: {record_id}")

        # 提取预诊信息
        height, weight, coze_conversation_log = None, None, None
        sanzhen_diagnosis = None
        if medical_record.pre_diagnosis:
            height = medical_record.pre_diagnosis.height
            weight = medical_record.pre_diagnosis.weight
            coze_conversation_log = medical_record.pre_diagnosis.coze_conversation_log
            if medical_record.pre_diagnosis.sanzhen_result:
                sanzhen_diagnosis = (
                    medical_record.pre_diagnosis.sanzhen_result.diagnosis_result
                )

        # 调用 TCM 服务
        tcm_service = tcm_service or (tcm_service_factory or get_tcm_service)()
        diagnosis_result = tcm_service.process_complete_diagnosis(
            transcript=diagnosis_data.asr_text,
            height=height,
            weight=weight,
            coze_conversation_log=coze_conversation_log,
            sanzhen_diagnosis=sanzhen_diagnosis,
        )

        if diagnosis_result["overall_status"] == "failed":
            raise DatabaseException(
                "AI诊断失败",
                diagnosis_result.get("error_message", "未知错误"),
            )

        # 创建 AI 诊断记录
        ai_diagnosis = await self.ai_diagnosis_repo.create_ai_diagnosis(
            record_id=record_id,
            formatted_medical_record=diagnosis_result["medical_record_result"].get(
                "medical_record"
            ),
            type_inference=diagnosis_result["diagnosis_result"].get("diagnosis"),
            prescription=diagnosis_result["prescription_result"].get("prescription"),
            exercise_prescription=diagnosis_result["exercise_prescription_result"].get(
                "exercise_prescription"
            ),
            diagnosis_explanation=diagnosis_result["diagnosis_result"].get(
                "diagnosis_explanation"
            ),
            response_time=diagnosis_result.get("total_processing_time"),
            model_name=settings.AI_MODEL_NAME,
        )

        await self.record_repo.update_status(medical_record, "completed")
        await self.db.commit()
        await self.ai_diagnosis_repo.refresh(ai_diagnosis)

        return AIDiagnosisResponse.model_validate(ai_diagnosis)

    async def stream_ai_diagnosis(
        self,
        record_id: int,
        diagnosis_data: AIDiagnosisCreate,
    ) -> tuple[Any, dict]:
        """
        获取流式 AI 诊断的输入数据

        Args:
            record_id: 就诊记录ID
            diagnosis_data: 诊断输入数据

        Returns:
            tuple: (医疗记录, 诊断参数字典)

        Raises:
            NotFoundException: 就诊记录不存在
        """
        medical_record = await self.record_repo.get_by_record_id(
            record_id, load_pre_diagnosis=True
        )
        if not medical_record:
            raise NotFoundException(f"未找到就诊记录 ID: {record_id}")

        # 提取预诊信息
        params: dict[str, float | str | None] = {
            "height": None,
            "weight": None,
            "coze_conversation_log": None,
            "sanzhen_diagnosis": None,
        }

        if medical_record.pre_diagnosis:
            params["height"] = medical_record.pre_diagnosis.height
            params["weight"] = medical_record.pre_diagnosis.weight
            params["coze_conversation_log"] = (
                medical_record.pre_diagnosis.coze_conversation_log
            )
            if medical_record.pre_diagnosis.sanzhen_result:
                params["sanzhen_diagnosis"] = (
                    medical_record.pre_diagnosis.sanzhen_result.diagnosis_result
                )

        return medical_record, params

    async def save_stream_diagnosis_result(
        self,
        record_id: int,
        final_result: dict,
    ) -> AIDiagnosisRecord:
        """
        保存流式诊断结果

        Args:
            record_id: 就诊记录ID
            final_result: 诊断结果数据

        Returns:
            AIDiagnosisRecord: 保存的 AI 诊断记录
        """
        medical_record = await self.record_repo.get_by_record_id(record_id)
        if medical_record is None:
            raise NotFoundException()

        ai_diagnosis = await self.ai_diagnosis_repo.create_ai_diagnosis(
            record_id=record_id,
            formatted_medical_record=final_result.get("formatted_medical_record"),
            type_inference=final_result.get("type_inference"),
            prescription=final_result.get("prescription"),
            exercise_prescription=final_result.get("exercise_prescription"),
            diagnosis_explanation=final_result.get("diagnosis_explanation"),
            response_time=final_result.get("total_processing_time"),
            model_name=settings.AI_MODEL_NAME,
        )

        if medical_record:
            await self.record_repo.update_status(medical_record, "completed")

        await self.db.commit()
        await self.ai_diagnosis_repo.refresh(ai_diagnosis)

        return ai_diagnosis

    async def create_doctor_diagnosis(
        self,
        record_id: int,
        doctor: Doctor,
        diagnosis_data: DoctorDiagnosisCreate,
    ) -> DoctorDiagnosisResponse:
        """
        创建医生诊断记录

        Args:
            record_id: 就诊记录ID
            doctor: 医生实体
            diagnosis_data: 诊断数据

        Returns:
            DoctorDiagnosisResponse: 医生诊断响应

        Raises:
            NotFoundException: 就诊记录不存在
            ValidationException: 状态不允许创建
        """
        medical_record = await self.record_repo.get_by_record_id(record_id)
        if not medical_record:
            raise NotFoundException(f"未找到就诊记录 ID: {record_id}")

        if medical_record.status == "confirmed":
            raise ValidationException(
                "无法创建医生诊断记录",
                "就诊记录已确认完成，不能再添加新的诊断记录",
            )

        # 初始化诊断字段
        formatted_medical_record = diagnosis_data.formatted_medical_record
        type_inference = diagnosis_data.type_inference
        treatment = diagnosis_data.treatment
        prescription = diagnosis_data.prescription
        exercise_prescription = diagnosis_data.exercise_prescription

        # 如果基于 AI 诊断，填充缺失字段
        if diagnosis_data.based_on_ai_diagnosis_id:
            ai_diagnosis = await self.ai_diagnosis_repo.get_by_diagnosis_and_record(
                diagnosis_data.based_on_ai_diagnosis_id,
                record_id,
            )
            if not ai_diagnosis:
                raise NotFoundException(
                    f"未找到AI诊断记录 ID: {diagnosis_data.based_on_ai_diagnosis_id}"
                )

            formatted_medical_record = (
                formatted_medical_record or ai_diagnosis.formatted_medical_record
            )
            type_inference = type_inference or ai_diagnosis.type_inference
            treatment = treatment or ai_diagnosis.treatment
            prescription = prescription or ai_diagnosis.prescription
            exercise_prescription = (
                exercise_prescription or ai_diagnosis.exercise_prescription
            )

        # 创建医生诊断
        doctor_diagnosis = await self.doctor_diagnosis_repo.create_doctor_diagnosis(
            record_id=record_id,
            doctor_id=doctor.doctor_id,
            formatted_medical_record=formatted_medical_record,
            type_inference=type_inference,
            treatment=treatment,
            prescription=prescription,
            exercise_prescription=exercise_prescription,
            comments=diagnosis_data.comments,
        )

        # 更新就诊记录状态
        if medical_record.status in ("pending", "completed"):
            await self.record_repo.update_status(medical_record, "in_progress")

        await self.db.commit()
        await self.doctor_diagnosis_repo.refresh(doctor_diagnosis)

        return DoctorDiagnosisResponse(
            diagnosis_id=doctor_diagnosis.diagnosis_id,
            record_id=doctor_diagnosis.record_id,
            type=SchemaDiagnosisType(doctor_diagnosis.type.value),
            doctor_id=doctor_diagnosis.doctor_id,
            doctor_name=doctor.name,
            formatted_medical_record=doctor_diagnosis.formatted_medical_record,
            type_inference=doctor_diagnosis.type_inference,
            treatment=doctor_diagnosis.treatment,
            prescription=doctor_diagnosis.prescription,
            exercise_prescription=doctor_diagnosis.exercise_prescription,
            comments=doctor_diagnosis.comments,
            created_at=doctor_diagnosis.created_at,
            updated_at=doctor_diagnosis.updated_at,
        )

    async def update_doctor_diagnosis(
        self,
        diagnosis_id: int,
        doctor: Doctor,
        diagnosis_data: DoctorDiagnosisUpdate,
    ) -> DoctorDiagnosisResponse:
        """
        更新医生诊断记录

        Args:
            diagnosis_id: 诊断记录ID
            doctor: 医生实体
            diagnosis_data: 更新数据

        Returns:
            DoctorDiagnosisResponse: 更新后的诊断响应

        Raises:
            NotFoundException: 诊断记录不存在
            ValidationException: 无权修改或状态不允许
        """
        doctor_diagnosis = await self.doctor_diagnosis_repo.get_by_diagnosis_id(
            diagnosis_id, load_medical_record=True
        )

        if not doctor_diagnosis:
            raise NotFoundException(f"未找到医生诊断记录 ID: {diagnosis_id}")

        if doctor_diagnosis.doctor_id != doctor.doctor_id:
            raise ValidationException(
                "无权修改此诊断记录", "只能修改自己创建的诊断记录"
            )

        if doctor_diagnosis.medical_record.status == "confirmed":
            raise ValidationException(
                "无法修改已确认的诊断记录",
                "就诊记录已确认完成，不能再修改",
            )

        # 更新字段
        update_data = diagnosis_data.model_dump(exclude_unset=True)
        await self.doctor_diagnosis_repo.update_fields(doctor_diagnosis, **update_data)
        await self.db.commit()
        await self.doctor_diagnosis_repo.refresh(doctor_diagnosis)

        return DoctorDiagnosisResponse(
            diagnosis_id=doctor_diagnosis.diagnosis_id,
            record_id=doctor_diagnosis.record_id,
            type=SchemaDiagnosisType(doctor_diagnosis.type.value),
            doctor_id=doctor_diagnosis.doctor_id,
            doctor_name=doctor.name,
            formatted_medical_record=doctor_diagnosis.formatted_medical_record,
            type_inference=doctor_diagnosis.type_inference,
            treatment=doctor_diagnosis.treatment,
            prescription=doctor_diagnosis.prescription,
            exercise_prescription=doctor_diagnosis.exercise_prescription,
            comments=doctor_diagnosis.comments,
            created_at=doctor_diagnosis.created_at,
            updated_at=doctor_diagnosis.updated_at,
        )

    async def get_doctor_diagnosis(
        self,
        diagnosis_id: int,
    ) -> DoctorDiagnosisResponse:
        """
        获取医生诊断记录详情

        Args:
            diagnosis_id: 诊断记录ID

        Returns:
            DoctorDiagnosisResponse: 诊断详情

        Raises:
            NotFoundException: 诊断记录不存在
        """
        doctor_diagnosis = await self.doctor_diagnosis_repo.get_by_diagnosis_id(
            diagnosis_id, load_doctor=True
        )

        if not doctor_diagnosis:
            raise NotFoundException(f"未找到医生诊断记录 ID: {diagnosis_id}")

        return DoctorDiagnosisResponse(
            diagnosis_id=doctor_diagnosis.diagnosis_id,
            record_id=doctor_diagnosis.record_id,
            type=SchemaDiagnosisType(doctor_diagnosis.type.value),
            doctor_id=doctor_diagnosis.doctor_id,
            doctor_name=(
                doctor_diagnosis.doctor.name if doctor_diagnosis.doctor else None
            ),
            formatted_medical_record=doctor_diagnosis.formatted_medical_record,
            type_inference=doctor_diagnosis.type_inference,
            treatment=doctor_diagnosis.treatment,
            prescription=doctor_diagnosis.prescription,
            exercise_prescription=doctor_diagnosis.exercise_prescription,
            comments=doctor_diagnosis.comments,
            created_at=doctor_diagnosis.created_at,
            updated_at=doctor_diagnosis.updated_at,
        )
