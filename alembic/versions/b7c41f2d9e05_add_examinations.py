"""add examinations columns for physical examination results

Revision ID: b7c41f2d9e05
Revises: d32e4c7f91ab
Create Date: 2026-11-09

脉象、舌象等客观体征改为由病案直接提供，患者对话不再负责「描述脉象」。
新增两列：medical_cases.examinations（体征数据）、training_sessions.examinations_done（已做过的检查）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b7c41f2d9e05"
down_revision: Union[str, Sequence[str], None] = "d32e4c7f91ab"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "medical_cases" in tables:
        existing = {c["name"] for c in inspector.get_columns("medical_cases")}
        if "examinations" not in existing:
            op.add_column("medical_cases", sa.Column("examinations", sa.JSON(), nullable=True))

    if "training_sessions" in tables:
        existing = {c["name"] for c in inspector.get_columns("training_sessions")}
        if "examinations_done" not in existing:
            op.add_column(
                "training_sessions",
                sa.Column("examinations_done", sa.JSON(), nullable=True),
            )


def downgrade() -> None:
    raise RuntimeError(
        "该迁移只新增可空列，回退会丢失已记录的体征数据，故不提供自动降级。"
    )
