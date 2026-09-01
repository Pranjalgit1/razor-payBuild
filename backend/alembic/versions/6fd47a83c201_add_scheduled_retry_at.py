"""add durable scheduled retry timestamp

Revision ID: 6fd47a83c201
Revises: 213bb5ec98a1
Create Date: 2026-09-01 21:45:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import app.database.base

revision: str = "6fd47a83c201"
down_revision: Union[str, Sequence[str], None] = "213bb5ec98a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("recovery_cases", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "scheduled_retry_at",
                app.database.base.UTCDateTime(timezone=True),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("recovery_cases", schema=None) as batch_op:
        batch_op.drop_column("scheduled_retry_at")
