"""immutable audit logs

Revision ID: 20260421_02
Revises: 20260421_01
Create Date: 2026-04-21 14:08:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "20260421_02"
down_revision = "20260421_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create the function
    op.execute("""
        CREATE OR REPLACE FUNCTION prevent_audit_log_modification()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'AuditLog entries are immutable and cannot be modified or deleted.';
        END;
        $$ LANGUAGE plpgsql;
    """)

    # 2. Add the trigger to audit_logs table
    op.execute("""
        CREATE TRIGGER trg_prevent_audit_log_modification
        BEFORE UPDATE OR DELETE ON audit_logs
        FOR EACH ROW
        EXECUTE FUNCTION prevent_audit_log_modification();
    """)


def downgrade() -> None:
    # 1. Drop trigger
    op.execute("DROP TRIGGER IF EXISTS trg_prevent_audit_log_modification ON audit_logs;")
    
    # 2. Drop function
    op.execute("DROP FUNCTION IF EXISTS prevent_audit_log_modification();")
