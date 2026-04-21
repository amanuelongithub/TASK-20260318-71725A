"""remediation and drift resolution"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260421_03"
down_revision = "20260421_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add reset token fields to users
    op.add_column("users", sa.Column("reset_token", sa.String(length=128), nullable=True))
    op.add_column("users", sa.Column("reset_token_expires", sa.DateTime(), nullable=True))
    op.create_index(op.f("ix_users_reset_token"), "users", ["reset_token"], unique=False)

    # 2. Add audit_log_batch_signatures table
    op.create_table(
        "audit_log_batch_signatures",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("org_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("last_log_id", sa.Integer(), nullable=False),
        sa.Column("batch_hash", sa.String(length=128), nullable=False),
        sa.Column("signature", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(op.f("ix_audit_log_batch_signatures_org_id"), "audit_log_batch_signatures", ["org_id"], unique=False)

    # 3. Rename AuditLog.metadata to event_metadata
    # Using execute since rename_column can be tricky with JSON types in some alembic versions
    op.alter_column("audit_logs", "metadata", new_column_name="event_metadata")


def downgrade() -> None:
    op.alter_column("audit_logs", "event_metadata", new_column_name="metadata")
    op.drop_index(op.f("ix_audit_log_batch_signatures_org_id"), table_name="audit_log_batch_signatures")
    op.drop_table("audit_log_batch_signatures")
    op.drop_index(op.f("ix_users_reset_token"), table_name="users")
    op.drop_column("users", "reset_token_expires")
    op.drop_column("users", "reset_token")
