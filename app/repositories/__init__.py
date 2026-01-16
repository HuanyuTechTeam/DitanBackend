"""Repository 层模块导出"""
from app.repositories.base import BaseRepository
from app.repositories.patient_repository import PatientRepository
from app.repositories.medical_record_repository import (
    MedicalRecordRepository,
    PreDiagnosisRepository,
    SanzhenRepository,
)
from app.repositories.diagnosis_repository import (
    AIDiagnosisRepository,
    DoctorDiagnosisRepository,
)
from app.repositories.doctor_repository import DoctorRepository

__all__ = [
    "BaseRepository",
    "PatientRepository",
    "MedicalRecordRepository",
    "PreDiagnosisRepository",
    "SanzhenRepository",
    "AIDiagnosisRepository",
    "DoctorDiagnosisRepository",
    "DoctorRepository",
]
