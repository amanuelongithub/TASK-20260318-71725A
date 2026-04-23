"""Rename users.reset_token to users.reset_token_hash

Store only the HMAC-SHA256 hash of the password reset token, never the
plaintext.  Existing tokens are invalidated by this migration (any in-flight
reset will need to be re-issued via the admin endpoint).

Revision ID: 20260423_01
Revises: 20260422_09_persistence_idempotency_trigger
Create Date: 2026-04-23
"""
from alembic import op
import sqlalchemy as sa

revision = "20260423_01"
down_revision = "20260422_09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "reset_token",
            new_column_name="reset_token_hash",
            existing_type=sa.String(128),
            nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "reset_token_hash",
            new_column_name="reset_token",
            existing_type=sa.String(128),
            nullable=True,
        )
