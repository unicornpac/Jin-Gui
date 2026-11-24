"""add announcements table

Revision ID: e5f72a9c3d81
Revises: d9e63f4b2c18
Create Date: 2026-11-25

网站公告：只给学生看（首页横幅 + 训练页提示），手动开关控制上下线。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e5f72a9c3d81"
down_revision: Union[str, Sequence[str], None] = "d9e63f4b2c18"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "announcements" in set(inspector.get_table_names()):
        return
    op.create_table(
        "announcements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_announcements_id", "announcements", ["id"])


def downgrade() -> None:
    raise RuntimeError("公告表回退会丢失已发布内容，不提供自动降级。")
