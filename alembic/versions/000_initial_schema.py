"""Frozen pre-001 schema for empty database upgrades.

Existing databases stamped at 001 or later do not run this revision.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

gender = postgresql.ENUM("MALE", "FEMALE", "OTHER", name="gender", create_type=False)

revision = "000_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    gender.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "doctors",
        sa.Column("doctor_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(length=50), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("gender", gender, nullable=False),
        sa.Column("phone", sa.String(length=11), nullable=False),
        sa.Column("department", sa.String(length=100), nullable=True),
        sa.Column("position", sa.String(length=100), nullable=True),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("last_login", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("doctor_id"),
    )
    op.create_index(op.f("ix_doctors_phone"), "doctors", ["phone"], unique=True)
    op.create_index(op.f("ix_doctors_username"), "doctors", ["username"], unique=True)
    op.create_table(
        "patients",
        sa.Column("patient_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("sex", gender, nullable=False),
        sa.Column("birthday", sa.Date(), nullable=False),
        sa.Column("phone", sa.String(length=11), nullable=False),
        sa.PrimaryKeyConstraint("patient_id"),
    )
    op.create_index(op.f("ix_patients_phone"), "patients", ["phone"], unique=True)
    op.create_table(
        "chat_conversations",
        sa.Column("conversation_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("patient_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patients.patient_id"],
        ),
        sa.PrimaryKeyConstraint("conversation_id"),
    )
    op.create_index(
        op.f("ix_chat_conversations_patient_id"),
        "chat_conversations",
        ["patient_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_chat_conversations_session_id"),
        "chat_conversations",
        ["session_id"],
        unique=True,
    )
    op.create_table(
        "patient_medical_records",
        sa.Column("record_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("patient_id", sa.Integer(), nullable=False),
        sa.Column("uuid", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patients.patient_id"],
        ),
        sa.PrimaryKeyConstraint("record_id"),
    )
    op.create_index(
        op.f("ix_patient_medical_records_patient_id"),
        "patient_medical_records",
        ["patient_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_patient_medical_records_uuid"),
        "patient_medical_records",
        ["uuid"],
        unique=True,
    )
    op.create_table(
        "chat_messages",
        sa.Column("message_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column(
            "role",
            sa.Enum("SYSTEM", "USER", "ASSISTANT", name="messagerole"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tokens", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["chat_conversations.conversation_id"],
        ),
        sa.PrimaryKeyConstraint("message_id"),
    )
    op.create_index(
        op.f("ix_chat_messages_conversation_id"),
        "chat_messages",
        ["conversation_id"],
        unique=False,
    )
    op.create_table(
        "diagnosis_records",
        sa.Column("diagnosis_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("record_id", sa.Integer(), nullable=False),
        sa.Column(
            "type",
            sa.Enum("AI_DIAGNOSIS", "DOCTOR_DIAGNOSIS", name="diagnosistype"),
            nullable=False,
        ),
        sa.Column("formatted_medical_record", sa.Text(), nullable=True),
        sa.Column("type_inference", sa.Text(), nullable=True),
        sa.Column("treatment", sa.Text(), nullable=True),
        sa.Column("prescription", sa.Text(), nullable=True),
        sa.Column("exercise_prescription", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["record_id"],
            ["patient_medical_records.record_id"],
        ),
        sa.PrimaryKeyConstraint("diagnosis_id"),
    )
    op.create_index(
        op.f("ix_diagnosis_records_record_id"),
        "diagnosis_records",
        ["record_id"],
        unique=False,
    )
    op.create_table(
        "pre_diagnosis_records",
        sa.Column("pre_diagnosis_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("record_id", sa.Integer(), nullable=False),
        sa.Column("uuid", sa.String(length=36), nullable=False),
        sa.Column("height", sa.Float(), nullable=True),
        sa.Column("weight", sa.Float(), nullable=True),
        sa.Column("coze_conversation_log", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["record_id"],
            ["patient_medical_records.record_id"],
        ),
        sa.PrimaryKeyConstraint("pre_diagnosis_id"),
    )
    op.create_index(
        op.f("ix_pre_diagnosis_records_record_id"),
        "pre_diagnosis_records",
        ["record_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_pre_diagnosis_records_uuid"),
        "pre_diagnosis_records",
        ["uuid"],
        unique=True,
    )
    op.create_table(
        "ai_diagnosis_records",
        sa.Column("diagnosis_id", sa.Integer(), nullable=False),
        sa.Column("diagnosis_explanation", sa.Text(), nullable=True),
        sa.Column("response_time", sa.Float(), nullable=True),
        sa.Column("model_name", sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(
            ["diagnosis_id"],
            ["diagnosis_records.diagnosis_id"],
        ),
        sa.PrimaryKeyConstraint("diagnosis_id"),
    )
    op.create_table(
        "doctor_diagnosis_records",
        sa.Column("diagnosis_id", sa.Integer(), nullable=False),
        sa.Column("doctor_id", sa.Integer(), nullable=False),
        sa.Column("comments", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["diagnosis_id"],
            ["diagnosis_records.diagnosis_id"],
        ),
        sa.ForeignKeyConstraint(
            ["doctor_id"],
            ["doctors.doctor_id"],
        ),
        sa.PrimaryKeyConstraint("diagnosis_id"),
    )
    op.create_index(
        op.f("ix_doctor_diagnosis_records_doctor_id"),
        "doctor_diagnosis_records",
        ["doctor_id"],
        unique=False,
    )
    op.create_table(
        "sanzhen_analysis_results",
        sa.Column("sanzhen_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("pre_diagnosis_id", sa.Integer(), nullable=False),
        sa.Column("face", sa.Text(), nullable=True),
        sa.Column("tongue_front", sa.Text(), nullable=True),
        sa.Column("tongue_bottom", sa.Text(), nullable=True),
        sa.Column("pulse", sa.Text(), nullable=True),
        sa.Column("diagnosis_result", sa.String(length=1024), nullable=True),
        sa.ForeignKeyConstraint(
            ["pre_diagnosis_id"],
            ["pre_diagnosis_records.pre_diagnosis_id"],
        ),
        sa.PrimaryKeyConstraint("sanzhen_id"),
    )
    op.create_index(
        op.f("ix_sanzhen_analysis_results_pre_diagnosis_id"),
        "sanzhen_analysis_results",
        ["pre_diagnosis_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_sanzhen_analysis_results_pre_diagnosis_id"),
        table_name="sanzhen_analysis_results",
    )
    op.drop_table("sanzhen_analysis_results")
    op.drop_index(
        op.f("ix_doctor_diagnosis_records_doctor_id"),
        table_name="doctor_diagnosis_records",
    )
    op.drop_table("doctor_diagnosis_records")
    op.drop_table("ai_diagnosis_records")
    op.drop_index(
        op.f("ix_pre_diagnosis_records_uuid"), table_name="pre_diagnosis_records"
    )
    op.drop_index(
        op.f("ix_pre_diagnosis_records_record_id"), table_name="pre_diagnosis_records"
    )
    op.drop_table("pre_diagnosis_records")
    op.drop_index(
        op.f("ix_diagnosis_records_record_id"), table_name="diagnosis_records"
    )
    op.drop_table("diagnosis_records")
    op.drop_index(op.f("ix_chat_messages_conversation_id"), table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index(
        op.f("ix_patient_medical_records_uuid"), table_name="patient_medical_records"
    )
    op.drop_index(
        op.f("ix_patient_medical_records_patient_id"),
        table_name="patient_medical_records",
    )
    op.drop_table("patient_medical_records")
    op.drop_index(
        op.f("ix_chat_conversations_session_id"), table_name="chat_conversations"
    )
    op.drop_index(
        op.f("ix_chat_conversations_patient_id"), table_name="chat_conversations"
    )
    op.drop_table("chat_conversations")
    op.drop_index(op.f("ix_patients_phone"), table_name="patients")
    op.drop_table("patients")
    op.drop_index(op.f("ix_doctors_username"), table_name="doctors")
    op.drop_index(op.f("ix_doctors_phone"), table_name="doctors")
    op.drop_table("doctors")

    for name in ("gender", "messagerole", "diagnosistype"):
        postgresql.ENUM(name=name).drop(op.get_bind(), checkfirst=True)
