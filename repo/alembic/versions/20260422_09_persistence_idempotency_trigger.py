"""persistence idempotency trigger

Revision ID: 20260422_09
Revises: 20260422_08
Create Date: 2026-04-22 13:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '20260422_09'
down_revision = '20260422_08'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == 'postgresql':
        # 1. PostgreSQL Trigger
        op.execute("""
        CREATE OR REPLACE FUNCTION check_idempotency_24h() RETURNS TRIGGER AS $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM process_instances
                WHERE org_id = NEW.org_id
                  AND (business_id = NEW.business_id OR idempotency_key = NEW.idempotency_key)
                  AND created_at >= NOW() - INTERVAL '24 hours'
            ) THEN
                RAISE EXCEPTION 'duplicate_idempotency_24h';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """)
        
        op.execute("""
        CREATE TRIGGER validate_process_idempotency_24h
        BEFORE INSERT ON process_instances
        FOR EACH ROW EXECUTE FUNCTION check_idempotency_24h();
        """)
    elif dialect == 'sqlite':
        # 2. SQLite Trigger (for dev/test)
        # Using 'datetime' directly since SQLite doesn't have INTERVAL syntax like PG
        op.execute("""
        CREATE TRIGGER validate_process_idempotency_sqlite_24h
        BEFORE INSERT ON process_instances
        FOR EACH ROW
        BEGIN
            SELECT RAISE(ABORT, 'Persistence-layer violation: Duplicate business_id or idempotency_key within 24-hour window')
            WHERE EXISTS (
                SELECT 1 FROM process_instances
                WHERE org_id = NEW.org_id
                  AND (business_id = NEW.business_id OR idempotency_key = NEW.idempotency_key)
                  AND created_at >= datetime('now', '-24 hours')
            );
        END;
        """)


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    
    if dialect == 'sqlite':
        # SQLite
        op.execute("DROP TRIGGER IF EXISTS validate_process_idempotency_sqlite_24h")
    elif dialect == 'postgresql':
        # PostgreSQL
        op.execute("DROP TRIGGER IF EXISTS validate_process_idempotency_24h ON process_instances")
        op.execute("DROP FUNCTION IF EXISTS check_idempotency_24h")
