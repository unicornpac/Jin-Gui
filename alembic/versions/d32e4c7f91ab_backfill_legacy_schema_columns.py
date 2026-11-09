"""Backfill columns missing from legacy SQLite databases.

Revision ID: d32e4c7f91ab
Revises: bb356c8cc735
Create Date: 2026-08-06

The initial Alembic revision creates a complete schema for an empty database.
Existing JinGui databases, including the tracked seed snapshot, may already
contain these tables but lack columns that were historically added by the
application's lightweight migration routine.  ``create_all`` deliberately does
not alter existing tables, so this revision closes that compatibility gap.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d32e4c7f91ab"
down_revision: Union[str, Sequence[str], None] = "bb356c8cc735"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LEGACY_COLUMNS = {
    "classic_texts": (
        sa.Column("section", sa.String(length=100), nullable=True),
        sa.Column("article_number", sa.Integer(), nullable=True),
        sa.Column("order_index", sa.Integer(), nullable=True),
        sa.Column("verified", sa.Boolean(), nullable=True, server_default=sa.text("0")),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("raw_content", sa.Text(), nullable=True),
        sa.Column("layout_marker", sa.String(length=10), nullable=True),
        sa.Column("source_file", sa.String(length=500), nullable=True),
        sa.Column("source_hash", sa.String(length=64), nullable=True),
        sa.Column("source_offset", sa.Integer(), nullable=True),
        sa.Column("source_edition", sa.String(length=200), nullable=True),
        sa.Column("import_batch_id", sa.String(length=36), nullable=True),
    ),
    "documents": (
        sa.Column("error_message", sa.Text(), nullable=True),
    ),
}


def upgrade() -> None:
    """Add only columns absent from older database snapshots."""
    inspector = sa.inspect(op.get_bind())
    existing_tables = set(inspector.get_table_names())

    for table_name, columns in LEGACY_COLUMNS.items():
        if table_name not in existing_tables:
            continue

        existing_columns = {
            column["name"] for column in inspector.get_columns(table_name)
        }
        for column in columns:
            if column.name not in existing_columns:
                op.add_column(table_name, column)


def downgrade() -> None:
    """Refuse an unsafe downgrade that could discard pre-existing user data."""
    raise RuntimeError(
        "Legacy schema backfill cannot be downgraded safely because its columns "
        "may have existed before this Alembic revision."
    )
