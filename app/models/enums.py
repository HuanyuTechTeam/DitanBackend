"""公共枚举定义"""

from enum import Enum as PyEnum


class Gender(PyEnum):
    """性别枚举"""

    MALE = "MALE"
    FEMALE = "FEMALE"
    OTHER = "OTHER"


class DiagnosisType(PyEnum):
    """诊断类型枚举"""

    AI_DIAGNOSIS = "AI_DIAGNOSIS"
    DOCTOR_DIAGNOSIS = "DOCTOR_DIAGNOSIS"


class MedicalRecordStatus(PyEnum):
    """就诊记录状态枚举"""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CONFIRMED = "confirmed"
