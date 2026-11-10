"""add structured scoring fields

Revision ID: c8d52e3a1f47
Revises: b7c41f2d9e05
Create Date: 2026-11-09

评分从「一次 LLM 自由打分」改为「按要点逐条对照」：
- medical_cases.key_facts      问诊要点（完整度统计）
- medical_cases.scoring_points 评分要点（含权重、关键词、起始难度）
- training_sessions.evaluation 评价报告原文（此前未落库，重复打开会拿 decision_path 顶替）
- training_sessions.scoring    要点得分明细

四个字段都可空：未配置要点体系的病案继续沿用原来的 LLM 评分，行为不变。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c8d52e3a1f47"
down_revision: Union[str, Sequence[str], None] = "b7c41f2d9e05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "medical_cases" in tables:
        existing = {c["name"] for c in inspector.get_columns("medical_cases")}
        if "key_facts" not in existing:
            op.add_column("medical_cases", sa.Column("key_facts", sa.JSON(), nullable=True))
        if "scoring_points" not in existing:
            op.add_column("medical_cases", sa.Column("scoring_points", sa.JSON(), nullable=True))

    if "training_sessions" in tables:
        existing = {c["name"] for c in inspector.get_columns("training_sessions")}
        if "evaluation" not in existing:
            op.add_column("training_sessions", sa.Column("evaluation", sa.Text(), nullable=True))
        if "scoring" not in existing:
            op.add_column("training_sessions", sa.Column("scoring", sa.JSON(), nullable=True))


def downgrade() -> None:
    raise RuntimeError(
        "该迁移只新增可空列，回退会丢失已录入的要点与评价记录，故不提供自动降级。"
    )
