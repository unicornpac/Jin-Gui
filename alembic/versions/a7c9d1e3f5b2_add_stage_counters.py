"""add per-stage wrong counters and revealed-stage flags

Revision ID: a7c9d1e3f5b2
Revises: f4a1b2c3d4e5
Create Date: 2026-11-27

中高级训练改为分关卡：每关独立计错，满 3 次由患者公布答案并强制过关。
初级沿用「连错 3 次结束」，仍复用原有 wrong_diagnosis_count（读辨病这一关）。

- stage_wrong_counts: {"辨病":0,"平脉":0,"析证":0,"定治":0}
- revealed_stages:    ["辨病","平脉"]，被公布过答案的关卡不计分
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7c9d1e3f5b2"
down_revision: Union[str, None] = "f4a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "training_sessions",
        sa.Column("stage_wrong_counts", sa.JSON(), nullable=True,
                  comment="各关卡连续答错次数"),
    )
    op.add_column(
        "training_sessions",
        sa.Column("revealed_stages", sa.JSON(), nullable=True,
                  comment="已由患者公布答案的关卡（不计分）"),
    )


def downgrade() -> None:
    op.drop_column("training_sessions", "revealed_stages")
    op.drop_column("training_sessions", "stage_wrong_counts")
