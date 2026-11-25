"""add page_visits table

Revision ID: f6a82b1d3e94
Revises: e5f72a9c3d81
Create Date: 2026-11-25

学生端页面访问统计：只记 /user、/train、/study 三个页面。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f6a82b1d3e94"
down_revision: Union[str, Sequence[str], None] = "f4a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "page_visits" in set(inspector.get_table_names()):
        return
    op.create_table(
        "page_visits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("path", sa.String(length=120), nullable=False),
        sa.Column("client_ip", sa.String(length=64)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_page_visits_id", "page_visits", ["id"])
    op.create_index("ix_page_visits_path", "page_visits", ["path"])
    op.create_index("ix_page_visits_created_at", "page_visits", ["created_at"])


def downgrade() -> None:
    raise RuntimeError("访问记录用于统计，不提供自动降级。")
