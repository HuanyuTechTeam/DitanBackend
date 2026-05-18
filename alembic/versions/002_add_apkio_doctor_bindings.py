"""添加 Apkio 医生身份绑定字段

Revision ID: 002_add_apkio_doctor_bindings
Revises: 001_add_sanzhen_image_urls
Create Date: 2026-05-18

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "002_add_apkio_doctor_bindings"
down_revision: Union[str, None] = "001_add_sanzhen_image_urls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """添加医生与 Apkio Org 用户的显式绑定。"""
    op.add_column("doctors", sa.Column("apkio_org_id", sa.String(36), nullable=True))
    op.add_column("doctors", sa.Column("apkio_user_id", sa.String(36), nullable=True))
    op.add_column("doctors", sa.Column("apkio_email", sa.String(255), nullable=True))
    op.create_index("ix_doctors_apkio_org_id", "doctors", ["apkio_org_id"])
    op.create_index("ix_doctors_apkio_user_id", "doctors", ["apkio_user_id"])
    op.create_index("ix_doctors_apkio_email", "doctors", ["apkio_email"])
    op.create_unique_constraint(
        "uq_doctors_apkio_org_user",
        "doctors",
        ["apkio_org_id", "apkio_user_id"],
    )


def downgrade() -> None:
    """移除医生与 Apkio Org 用户的显式绑定。"""
    op.drop_constraint("uq_doctors_apkio_org_user", "doctors", type_="unique")
    op.drop_index("ix_doctors_apkio_email", table_name="doctors")
    op.drop_index("ix_doctors_apkio_user_id", table_name="doctors")
    op.drop_index("ix_doctors_apkio_org_id", table_name="doctors")
    op.drop_column("doctors", "apkio_email")
    op.drop_column("doctors", "apkio_user_id")
    op.drop_column("doctors", "apkio_org_id")
