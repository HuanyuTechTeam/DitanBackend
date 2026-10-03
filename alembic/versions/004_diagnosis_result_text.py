"""Allow diagnosis reports longer than 1024 characters.

Revision ID: 004_diagnosis_result_text
Revises: 003_org_medical_upload
"""

from alembic import op
import sqlalchemy as sa

revision = "004_diagnosis_result_text"
down_revision = "003_org_medical_upload"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "sanzhen_analysis_results",
        "diagnosis_result",
        existing_type=sa.String(1024),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    # Downgrading truncates reports to their first 1024 characters; data is lost.
    op.alter_column(
        "sanzhen_analysis_results",
        "diagnosis_result",
        existing_type=sa.Text(),
        type_=sa.String(1024),
        existing_nullable=True,
        postgresql_using="left(diagnosis_result, 1024)",
    )
