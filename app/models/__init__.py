"""数据库模型导出"""

from app.models.enums import Gender, DiagnosisType, MedicalRecordStatus
from app.models.doctor import Doctor
from app.models.medical import (
    Patient,
    PatientMedicalRecord,
    PreDiagnosisRecord,
    SanzhenAnalysisResult,
    DiagnosisRecord,
    AIDiagnosisRecord,
    DoctorDiagnosisRecord,
)
from app.models.chat import (
    MessageRole,
    ChatConversation,
    ChatMessage,
)
from app.models.consultation import (
    Consultation, ConsultationTurn, ConsultationMessage, ConsultationLLMCall,
)

__all__ = [
    "Gender",
    "DiagnosisType",
    "MedicalRecordStatus",
    "Doctor",
    "Patient",
    "PatientMedicalRecord",
    "PreDiagnosisRecord",
    "SanzhenAnalysisResult",
    "DiagnosisRecord",
    "AIDiagnosisRecord",
    "DoctorDiagnosisRecord",
    # Chat models
    "MessageRole",
    "ChatConversation",
    "ChatMessage",
    "Consultation",
    "ConsultationTurn",
    "ConsultationMessage",
    "ConsultationLLMCall",
]
