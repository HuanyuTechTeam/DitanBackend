"""患者与就诊相关数据库模型"""

from datetime import datetime, date
from typing import Optional, List

from sqlalchemy import (
    String,
    Text,
    DateTime,
    Date,
    Float,
    Integer,
    ForeignKey,
    Enum,
    UniqueConstraint,
    ForeignKeyConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import Gender, DiagnosisType


class Patient(Base):
    """患者基本信息"""

    __tablename__ = "patients"
    __table_args__ = (
        UniqueConstraint("org_id", "phone", name="uq_patients_org_phone"),
        UniqueConstraint("org_id", "patient_id", name="uq_patients_org_id"),
    )
    org_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)

    patient_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    sex: Mapped[Gender] = mapped_column(Enum(Gender), nullable=False)
    birthday: Mapped[date] = mapped_column(Date, nullable=False)
    phone: Mapped[str] = mapped_column(String(11), nullable=False, index=True)

    medical_records: Mapped[List["PatientMedicalRecord"]] = relationship(
        "PatientMedicalRecord", back_populates="patient", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Patient(patient_id={self.patient_id}, name={self.name})>"


class PatientMedicalRecord(Base):
    """就诊记录"""

    __tablename__ = "patient_medical_records"
    __table_args__ = (
        UniqueConstraint("org_id", "uuid", name="uq_medical_records_org_uuid"),
        UniqueConstraint("org_id", "record_id", name="uq_medical_records_org_id"),
        ForeignKeyConstraint(
            ["org_id", "patient_id"],
            ["patients.org_id", "patients.patient_id"],
            name="fk_medical_records_org_patient",
        ),
    )
    org_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    upload_digest: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    upload_user_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    upload_device_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    upload_client_session_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    upload_request_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)

    record_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    patient_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    uuid: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    patient: Mapped["Patient"] = relationship(
        "Patient", back_populates="medical_records"
    )
    pre_diagnosis: Mapped[Optional["PreDiagnosisRecord"]] = relationship(
        "PreDiagnosisRecord",
        back_populates="medical_record",
        uselist=False,
        cascade="all, delete-orphan",
    )
    diagnoses: Mapped[List["DiagnosisRecord"]] = relationship(
        "DiagnosisRecord", back_populates="medical_record", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<PatientMedicalRecord(record_id={self.record_id}, status={self.status})>"
        )


class PreDiagnosisRecord(Base):
    """预诊记录"""

    __tablename__ = "pre_diagnosis_records"
    __table_args__ = (
        UniqueConstraint("org_id", "uuid", name="uq_pre_diagnosis_org_uuid"),
        ForeignKeyConstraint(
            ["org_id", "record_id"],
            ["patient_medical_records.org_id", "patient_medical_records.record_id"],
            name="fk_pre_diagnosis_org_record",
        ),
    )
    org_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)

    pre_diagnosis_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    record_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        unique=True,
        index=True,
    )
    uuid: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    height: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    weight: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    coze_conversation_log: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    medical_record: Mapped["PatientMedicalRecord"] = relationship(
        "PatientMedicalRecord", back_populates="pre_diagnosis"
    )
    sanzhen_result: Mapped[Optional["SanzhenAnalysisResult"]] = relationship(
        "SanzhenAnalysisResult",
        back_populates="pre_diagnosis",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<PreDiagnosisRecord(pre_diagnosis_id={self.pre_diagnosis_id})>"


class SanzhenAnalysisResult(Base):
    """三诊分析结果"""

    __tablename__ = "sanzhen_analysis_results"

    sanzhen_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    pre_diagnosis_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("pre_diagnosis_records.pre_diagnosis_id"),
        nullable=False,
        unique=True,
        index=True,
    )
    face: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    face_image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    tongue_front: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tongue_front_image_url: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
    )
    tongue_bottom: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tongue_bottom_image_url: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
    )
    pulse: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    diagnosis_result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    pre_diagnosis: Mapped["PreDiagnosisRecord"] = relationship(
        "PreDiagnosisRecord", back_populates="sanzhen_result"
    )

    def __repr__(self) -> str:
        return f"<SanzhenAnalysisResult(sanzhen_id={self.sanzhen_id})>"


class DiagnosisRecord(Base):
    """诊断记录基类"""

    __tablename__ = "diagnosis_records"

    diagnosis_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    record_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("patient_medical_records.record_id"),
        nullable=False,
        index=True,
    )
    type: Mapped[DiagnosisType] = mapped_column(Enum(DiagnosisType), nullable=False)
    formatted_medical_record: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    type_inference: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    treatment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    prescription: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    exercise_prescription: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    __mapper_args__ = {
        "polymorphic_identity": "diagnosis_record",
        "polymorphic_on": "type",
    }

    medical_record: Mapped["PatientMedicalRecord"] = relationship(
        "PatientMedicalRecord", back_populates="diagnoses"
    )

    def __repr__(self) -> str:
        return f"<DiagnosisRecord(diagnosis_id={self.diagnosis_id}, type={self.type})>"


class AIDiagnosisRecord(DiagnosisRecord):
    """AI诊断记录"""

    __tablename__ = "ai_diagnosis_records"

    diagnosis_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("diagnosis_records.diagnosis_id"), primary_key=True
    )
    diagnosis_explanation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    response_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    model_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    __mapper_args__ = {"polymorphic_identity": DiagnosisType.AI_DIAGNOSIS}

    def __repr__(self) -> str:
        return f"<AIDiagnosisRecord(diagnosis_id={self.diagnosis_id})>"


class DoctorDiagnosisRecord(DiagnosisRecord):
    """医生诊断记录"""

    __tablename__ = "doctor_diagnosis_records"

    diagnosis_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("diagnosis_records.diagnosis_id"), primary_key=True
    )
    doctor_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("doctors.doctor_id"), nullable=False, index=True
    )
    comments: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __mapper_args__ = {"polymorphic_identity": DiagnosisType.DOCTOR_DIAGNOSIS}

    doctor: Mapped["Doctor"] = relationship(
        "Doctor", back_populates="diagnosis_records"
    )

    def __repr__(self) -> str:
        return f"<DoctorDiagnosisRecord(diagnosis_id={self.diagnosis_id})>"


# 为了避免循环导入，在文件末尾导入
from app.models.doctor import Doctor  # noqa: E402, F811
