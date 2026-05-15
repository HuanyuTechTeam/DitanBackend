"""添加三诊图片URL字段

Revision ID: 001_add_sanzhen_image_urls
Revises:
Create Date: 2024-12-18

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "001_add_sanzhen_image_urls"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """添加面部图片URL、舌面图片URL、舌底图片URL字段"""
    op.add_column(
        "sanzhen_analysis_results",
        sa.Column("face_image_url", sa.String(500), nullable=True),
    )
    op.add_column(
        "sanzhen_analysis_results",
        sa.Column("tongue_front_image_url", sa.String(500), nullable=True),
    )
    op.add_column(
        "sanzhen_analysis_results",
        sa.Column("tongue_bottom_image_url", sa.String(500), nullable=True),
    )


def downgrade() -> None:
    """移除图片URL字段"""
    op.drop_column("sanzhen_analysis_results", "tongue_bottom_image_url")
    op.drop_column("sanzhen_analysis_results", "tongue_front_image_url")
    op.drop_column("sanzhen_analysis_results", "face_image_url")
