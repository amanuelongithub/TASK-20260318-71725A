"""remediation schema sync

Revision ID: 20260422_05
Revises: 20260422_04
Create Date: 2026-04-22 02:50:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '20260422_05'
down_revision = '20260422_04'
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != 'sqlite':
        # Use IF EXISTS — on a fresh DB this constraint may not exist if the
        # earlier migration that created it was never applied.
        op.execute(
            "ALTER TABLE process_instances DROP CONSTRAINT IF EXISTS uq_org_idempotency"
        )

    # 2. Add indexes for ProcessInstance
    op.create_index(op.f('ix_process_instances_created_at'), 'process_instances', ['created_at'], unique=False)
    op.create_index(op.f('ix_process_instances_completed_at'), 'process_instances', ['completed_at'], unique=False)
    op.create_index(op.f('ix_process_instances_sla_due_at'), 'process_instances', ['sla_due_at'], unique=False)

    # 3. Add indexes for Task
    op.create_index(op.f('ix_tasks_created_at'), 'tasks', ['created_at'], unique=False)
    op.create_index(op.f('ix_tasks_completed_at'), 'tasks', ['completed_at'], unique=False)
    op.create_index(op.f('ix_tasks_sla_due_at'), 'tasks', ['sla_due_at'], unique=False)

    # 4. Add index for AuditLog
    op.create_index(op.f('ix_audit_logs_created_at'), 'audit_logs', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_audit_logs_created_at'), table_name='audit_logs')
    op.drop_index(op.f('ix_tasks_sla_due_at'), table_name='tasks')
    op.drop_index(op.f('ix_tasks_completed_at'), table_name='tasks')
    op.drop_index(op.f('ix_tasks_created_at'), table_name='tasks')
    op.drop_index(op.f('ix_process_instances_sla_due_at'), table_name='process_instances')
    op.drop_index(op.f('ix_process_instances_completed_at'), table_name='process_instances')
    op.drop_index(op.f('ix_process_instances_created_at'), table_name='process_instances')
    op.create_unique_constraint('uq_org_idempotency', 'process_instances', ['org_id', 'idempotency_key'])
