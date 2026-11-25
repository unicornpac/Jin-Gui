"""add wrong diagnosis counter for the three-strike rule

Revision ID: f4a1b2c3d4e5
Revises: e5f72a9c3d81
Create Date: 2026-11-25

辨病连续答错三次强制结束会话。计数器随会话重置，可空，旧会话按 0 处理。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f4a1b2c3d4e5"
down_revision: Union[str, None] = "e5f72a9c3d81"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "training_sessions",
        sa.Column("wrong_diagnosis_count", sa.Integer(), nullable=False,
                  server_default="0", comment="辨病连续答错次数"),
    )


def downgrade() -> None:
    op.drop_column("training_sessions", "wrong_diagnosis_count")
