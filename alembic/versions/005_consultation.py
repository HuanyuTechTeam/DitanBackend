"""Persist consultations and fenced turn attempts.

Revision ID: 005_consultation
Revises: 004_diagnosis_result_text
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "005_consultation"
down_revision = "004_diagnosis_result_text"
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(JSONB(), "postgresql")
ID_TYPE = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def child_columns():
    return [
        sa.Column("id", ID_TYPE, primary_key=True, autoincrement=True),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("consultation_id", sa.String(36), nullable=False),
        sa.Column("turn_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    ]


def parent_fk(name):
    return sa.ForeignKeyConstraint(
        ["org_id", "consultation_id"],
        ["consultations.org_id", "consultations.id"],
        name=name,
    )


def upgrade() -> None:
    op.create_table(
        "consultations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("encounter_uuid", sa.String(36), nullable=False),
        sa.Column("pre_diagnosis_uuid", sa.String(36)),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("workflow_version", sa.Text(), nullable=False),
        sa.Column("inputs", JSON_TYPE, nullable=False),
        sa.Column("user_input_text", sa.Text()),
        sa.Column("workflow_state", JSON_TYPE, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("report_text", sa.Text()),
        sa.Column("created_by_user_id", sa.Text(), nullable=False),
        sa.Column("created_by_device_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("org_id", "id", name="uq_consultations_org_id"),
    )
    op.create_index(
        "uq_consultations_active_encounter",
        "consultations",
        ["org_id", "encounter_uuid"],
        unique=True,
        postgresql_where=sa.text("status <> 'abandoned'"),
        sqlite_where=sa.text("status <> 'abandoned'"),
    )
    op.create_table(
        "consultation_turns",
        *child_columns(),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("input_text", sa.Text()),
        sa.Column("base_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_user_id", sa.Text(), nullable=False),
        sa.Column("actor_device_id", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        parent_fk("fk_consultation_turn_org"),
        sa.UniqueConstraint(
            "consultation_id", "turn_id", name="uq_consultation_turn_id"
        ),
    )
    op.create_index(
        "uq_consultation_processing",
        "consultation_turns",
        ["consultation_id"],
        unique=True,
        postgresql_where=sa.text("status = 'processing'"),
        sqlite_where=sa.text("status = 'processing'"),
    )
    op.create_table(
        "consultation_messages",
        *child_columns(),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("step_id", sa.Text()),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("meta", JSON_TYPE),
        parent_fk("fk_consultation_message_org"),
        sa.UniqueConstraint(
            "consultation_id", "seq", name="uq_consultation_message_seq"
        ),
    )
    op.create_table(
        "consultation_llm_calls",
        *child_columns(),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("step_id", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("request", JSON_TYPE, nullable=False),
        sa.Column("response", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("first_token_ms", sa.Integer()),
        sa.Column("prompt_tokens", sa.Integer()),
        sa.Column("completion_tokens", sa.Integer()),
        parent_fk("fk_consultation_llm_call_org"),
    )


def downgrade() -> None:
    for table in (
        "consultation_llm_calls",
        "consultation_messages",
        "consultation_turns",
        "consultations",
    ):
        op.drop_table(table)
