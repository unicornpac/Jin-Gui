"""initial — 创建所有表

Revision ID: bb356c8cc735
Revises:
Create Date: 2026-08-06
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'bb356c8cc735'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 从 SQLAlchemy 元数据创建所有表（适配现有模型）
    from app.database import Base
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    # 删除所有表
    from app.database import Base
    Base.metadata.drop_all(bind=op.get_bind())
