"""患者与就诊相关 Pydantic 模型"""

from datetime import datetime, date
from typing import Optional, List, Union

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.common import (
    Gender,
    DiagnosisType,
    PhoneValidatorMixin,
    UUIDValidatorMixin,
    APIResponse,
    ErrorResponse,
)


class PatientCreate(BaseModel, PhoneValidatorMixin):
    """创建患者请求"""

    name: str = Field(..., description="患者姓名")
    sex: Gender = Field(..., description="性别")
    birthday: date = Field(..., description="出生日期")
    phone: str = Field(..., description="手机号")

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return cls.validate_phone_format(v)


class PatientResponse(BaseModel):
    """患者响应"""

    patient_id: int
    name: str
    sex: Gender
    birthday: date
    phone: str

    model_config = {"from_attributes": True}


class SanzhenAnalysisCreate(BaseModel):
    """三诊分析结果创建"""

    face: Optional[str] = Field(None, description="面诊结果")
    face_image_url: Optional[str] = Field(None, description="面诊图片URL")
    tongue_front: Optional[str] = Field(None, description="舌诊正面结果")
    tongue_front_image_url: Optional[str] = Field(None, description="舌诊正面图片URL")
    tongue_bottom: Optional[str] = Field(None, description="舌诊舌下结果")
    tongue_bottom_image_url: Optional[str] = Field(None, description="舌诊舌下图片URL")
    pulse: Optional[str] = Field(None, description="脉诊结果")
    diagnosis_result: Optional[str] = Field(None, description="综合诊断结果")


class SanzhenAnalysisResponse(BaseModel):
    """三诊分析结果响应"""

    sanzhen_id: int
    face: Optional[str] = None
    face_image_url: Optional[str] = None
    tongue_front: Optional[str] = None
    tongue_front_image_url: Optional[str] = None
    tongue_bottom: Optional[str] = None
    tongue_bottom_image_url: Optional[str] = None
    pulse: Optional[str] = None
    diagnosis_result: Optional[str] = None

    model_config = {"from_attributes": True}


class PreDiagnosisCreate(BaseModel, UUIDValidatorMixin):
    """创建预诊记录请求"""

    uuid: str = Field(..., description="预诊记录UUID")
    height: Optional[float] = Field(None, allow_inf_nan=False, description="身高(cm)")
    weight: Optional[float] = Field(None, allow_inf_nan=False, description="体重(kg)")
    coze_conversation_log: Optional[str] = Field(None, description="对话记录")
    sanzhen_analysis: Optional[SanzhenAnalysisCreate] = Field(
        None, description="三诊分析结果"
    )

    @field_validator("uuid")
    @classmethod
    def validate_uuid(cls, v: str) -> str:
        return cls.validate_uuid_format(v)


class PreDiagnosisResponse(BaseModel):
    """预诊记录响应"""

    pre_diagnosis_id: int
    record_id: int
    uuid: str
    height: Optional[float] = None
    weight: Optional[float] = None
    coze_conversation_log: Optional[str] = None
    sanzhen_result: Optional[SanzhenAnalysisResponse] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MedicalRecordCreate(BaseModel, PhoneValidatorMixin, UUIDValidatorMixin):
    """创建就诊记录请求"""

    uuid: str = Field(..., description="就诊记录UUID")
    patient_phone: str = Field(..., description="患者手机号")
    patient_info: Optional[PatientCreate] = Field(
        None, description="患者信息（新患者需提供）"
    )
    pre_diagnosis: PreDiagnosisCreate = Field(..., description="预诊记录")

    @model_validator(mode="after")
    def consistent_phone(self) -> "MedicalRecordCreate":
        if (
            self.patient_info is not None
            and self.patient_info.phone != self.patient_phone
        ):
            raise ValueError("patient_phone and patient_info.phone must match")
        return self

    @field_validator("uuid")
    @classmethod
    def validate_uuid(cls, v: str) -> str:
        return cls.validate_uuid_format(v)

    @field_validator("patient_phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return cls.validate_phone_format(v)


class MedicalRecordResponse(BaseModel):
    """就诊记录响应"""

    record_id: int
    patient_id: int
    uuid: str
    status: str
    created_at: datetime
    updated_at: datetime
    patient: PatientResponse
    pre_diagnosis: Optional[PreDiagnosisResponse] = None

    model_config = {"from_attributes": True}


class MedicalRecordListItem(BaseModel):
    """就诊记录列表项"""

    record_id: int
    uuid: str
    status: str
    created_at: datetime
    patient_name: str
    patient_phone: str

    model_config = {"from_attributes": True}


class DiagnosisRecordBase(BaseModel):
    """诊断记录基类"""

    formatted_medical_record: Optional[str] = Field(None, description="格式化病历")
    type_inference: Optional[str] = Field(None, description="证型推断")
    treatment: Optional[str] = Field(None, description="治疗建议")
    prescription: Optional[str] = Field(None, description="处方")
    exercise_prescription: Optional[str] = Field(None, description="运动处方")


class AIDiagnosisCreate(DiagnosisRecordBase):
    """创建AI诊断请求"""

    asr_text: str = Field(..., description="ASR转录文本")


class AIDiagnosisResponse(DiagnosisRecordBase):
    """AI诊断响应"""

    diagnosis_id: int
    record_id: int
    type: DiagnosisType
    diagnosis_explanation: Optional[str] = None
    response_time: Optional[float] = None
    model_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DoctorDiagnosisCreate(BaseModel):
    """创建医生诊断请求"""

    based_on_ai_diagnosis_id: Optional[int] = Field(
        None, description="基于哪个AI诊断创建（可选，会复制AI诊断内容）"
    )
    formatted_medical_record: Optional[str] = Field(None, description="格式化病历")
    type_inference: Optional[str] = Field(None, description="证型推断")
    treatment: Optional[str] = Field(None, description="治疗建议")
    prescription: Optional[str] = Field(None, description="处方")
    exercise_prescription: Optional[str] = Field(None, description="运动处方")
    comments: Optional[str] = Field(None, description="医生备注")


class DoctorDiagnosisUpdate(BaseModel):
    """更新医生诊断请求"""

    formatted_medical_record: Optional[str] = Field(None, description="格式化病历")
    type_inference: Optional[str] = Field(None, description="证型推断")
    treatment: Optional[str] = Field(None, description="治疗建议")
    prescription: Optional[str] = Field(None, description="处方")
    exercise_prescription: Optional[str] = Field(None, description="运动处方")
    comments: Optional[str] = Field(None, description="医生备注")


class DoctorDiagnosisResponse(DiagnosisRecordBase):
    """医生诊断响应"""

    diagnosis_id: int
    record_id: int
    type: DiagnosisType
    doctor_id: int
    doctor_name: Optional[str] = None
    comments: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CompleteMedicalRecordResponse(BaseModel):
    """完整的就诊信息响应"""

    record_id: int
    uuid: str
    status: str
    created_at: datetime
    updated_at: datetime
    patient: PatientResponse
    pre_diagnosis: Optional[PreDiagnosisResponse] = None
    diagnoses: List[Union[AIDiagnosisResponse, DoctorDiagnosisResponse]] = Field(
        default_factory=list
    )

    model_config = {"from_attributes": True}


class PatientQueryResponse(BaseModel):
    """患者查询响应"""

    patient: PatientResponse
    medical_records: List[MedicalRecordListItem] = Field(
        default_factory=list, description="历史就诊记录"
    )

    model_config = {"from_attributes": True}


# 导出公共模型
__all__ = [
    "Gender",
    "DiagnosisType",
    "APIResponse",
    "ErrorResponse",
    "PatientCreate",
    "PatientResponse",
    "SanzhenAnalysisCreate",
    "SanzhenAnalysisResponse",
    "PreDiagnosisCreate",
    "PreDiagnosisResponse",
    "MedicalRecordCreate",
    "MedicalRecordResponse",
    "MedicalRecordListItem",
    "DiagnosisRecordBase",
    "AIDiagnosisCreate",
    "AIDiagnosisResponse",
    "DoctorDiagnosisCreate",
    "DoctorDiagnosisUpdate",
    "DoctorDiagnosisResponse",
    "CompleteMedicalRecordResponse",
    "PatientQueryResponse",
]
