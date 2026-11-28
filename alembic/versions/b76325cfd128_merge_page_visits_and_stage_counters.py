"""merge page visits and stage counters

Revision ID: b76325cfd128
Revises: a7c9d1e3f5b2, f6a82b1d3e94
Create Date: 2026-11-27 22:05:58.984735

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b76325cfd128'
down_revision: Union[str, Sequence[str], None] = ('a7c9d1e3f5b2', 'f6a82b1d3e94')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
