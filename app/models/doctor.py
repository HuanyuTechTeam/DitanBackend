"""医生相关数据库模型"""

from datetime import datetime
from typing import Optional, List, TYPE_CHECKING

from sqlalchemy import String, Text, DateTime, Integer, Enum, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import Gender

if TYPE_CHECKING:
    from app.models.medical import DoctorDiagnosisRecord


class Doctor(Base):
    """医生用户实体"""

    __tablename__ = "doctors"
    __table_args__ = (
        UniqueConstraint(
            "apkio_org_id",
            "apkio_user_id",
            name="uq_doctors_apkio_org_user",
        ),
    )

    doctor_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    username: Mapped[str] = mapped_column(
        String(50), nullable=False, unique=True, index=True
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    gender: Mapped[Gender] = mapped_column(Enum(Gender), nullable=False)
    phone: Mapped[str] = mapped_column(
        String(11), nullable=False, unique=True, index=True
    )
    department: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    position: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    bio: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    apkio_org_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True, index=True
    )
    apkio_user_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True, index=True
    )
    apkio_email: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    diagnosis_records: Mapped[List["DoctorDiagnosisRecord"]] = relationship(
        "DoctorDiagnosisRecord", back_populates="doctor", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Doctor(doctor_id={self.doctor_id}, username={self.username})>"
