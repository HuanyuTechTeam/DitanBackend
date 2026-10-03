"""Durable consultation state, attempts, committed messages and model audit."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")
ID_TYPE = BigInteger().with_variant(Integer(), "sqlite")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parent_fk(name: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["org_id", "consultation_id"],
        ["consultations.org_id", "consultations.id"],
        name=name,
    )


class Consultation(Base):
    __tablename__ = "consultations"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_consultations_org_id"),
        Index(
            "uq_consultations_active_encounter",
            "org_id",
            "encounter_uuid",
            unique=True,
            postgresql_where=text("status <> 'abandoned'"),
            sqlite_where=text("status <> 'abandoned'"),
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    org_id: Mapped[str] = mapped_column(Text)
    encounter_uuid: Mapped[str] = mapped_column(String(36))
    pre_diagnosis_uuid: Mapped[str | None] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(Text, default="collecting")
    workflow_version: Mapped[str] = mapped_column(Text, default="v1")
    inputs: Mapped[dict] = mapped_column(JSON_TYPE)
    user_input_text: Mapped[str | None] = mapped_column(Text)
    workflow_state: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    report_text: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[str] = mapped_column(Text)
    created_by_device_id: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConsultationTurn(Base):
    __tablename__ = "consultation_turns"
    __table_args__ = (
        parent_fk("fk_consultation_turn_org"),
        UniqueConstraint("consultation_id", "turn_id", name="uq_consultation_turn_id"),
        Index(
            "uq_consultation_processing",
            "consultation_id",
            unique=True,
            postgresql_where=text("status = 'processing'"),
            sqlite_where=text("status = 'processing'"),
        ),
    )

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    org_id: Mapped[str] = mapped_column(Text)
    consultation_id: Mapped[str] = mapped_column(String(36))
    turn_id: Mapped[str] = mapped_column(String(36))
    kind: Mapped[str] = mapped_column(Text)
    input_text: Mapped[str | None] = mapped_column(Text)
    base_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, default="processing")
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actor_user_id: Mapped[str] = mapped_column(Text)
    actor_device_id: Mapped[str] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConsultationMessage(Base):
    __tablename__ = "consultation_messages"
    __table_args__ = (
        parent_fk("fk_consultation_message_org"),
        UniqueConstraint("consultation_id", "seq", name="uq_consultation_message_seq"),
    )

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    org_id: Mapped[str] = mapped_column(Text)
    consultation_id: Mapped[str] = mapped_column(String(36))
    seq: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    step_id: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    turn_id: Mapped[str] = mapped_column(String(36))
    meta: Mapped[dict | None] = mapped_column(JSON_TYPE)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class ConsultationLLMCall(Base):
    __tablename__ = "consultation_llm_calls"
    __table_args__ = (parent_fk("fk_consultation_llm_call_org"),)

    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    org_id: Mapped[str] = mapped_column(Text)
    consultation_id: Mapped[str] = mapped_column(String(36))
    turn_id: Mapped[str] = mapped_column(String(36))
    attempt: Mapped[int] = mapped_column(Integer)
    purpose: Mapped[str] = mapped_column(Text)
    step_id: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    prompt_version: Mapped[str] = mapped_column(Text)
    request: Mapped[dict] = mapped_column(JSON_TYPE)
    response: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int] = mapped_column(Integer)
    first_token_ms: Mapped[int | None] = mapped_column(Integer)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
