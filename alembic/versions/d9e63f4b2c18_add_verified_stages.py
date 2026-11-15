"""add verified_stages for stage review cache

Revision ID: d9e63f4b2c18
Revises: c8d52e3a1f47
Create Date: 2026-11-13

进度判定加入模型复核后，需要记住「哪些阶段已经确认过」，
否则每轮都会重复调用模型。该列可空，旧会话按未复核处理，
行为与之前一致（规则直接判定）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d9e63f4b2c18"
down_revision: Union[str, Sequence[str], None] = "c8d52e3a1f47"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "training_sessions" not in set(inspector.get_table_names()):
        return
    existing = {c["name"] for c in inspector.get_columns("training_sessions")}
    if "verified_stages" not in existing:
        op.add_column("training_sessions",
                      sa.Column("verified_stages", sa.JSON(), nullable=True))


def downgrade() -> None:
    raise RuntimeError(
        "该迁移只新增可空列，回退会丢失复核缓存（不影响进度正确性），故不提供自动降级。"
    )
