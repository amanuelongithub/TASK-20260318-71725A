"""Add ResourceApplication and CreditChange domains

Revision ID: 20260422_06
Revises: 8aa4006e3ed0
Create Date: 2026-04-22 03:26:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260422_06'
down_revision = '8aa4006e3ed0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Resource Applications Table
    op.create_table(
        'resource_applications',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('org_id', sa.Integer(), nullable=False),
        sa.Column('application_number', sa.String(length=64), nullable=False),
        sa.Column('resource_name', sa.String(length=255), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('applicant_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='pending'),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
        sa.ForeignKeyConstraint(['applicant_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    # Explicit business index requirements: Unique business number per Org
    op.create_index('uq_org_resource_app_num', 'resource_applications', ['org_id', 'application_number'], unique=True)
    # Performance indexes for status and time-based queries
    op.create_index(op.f('ix_resource_applications_status'), 'resource_applications', ['status'], unique=False)
    op.create_index(op.f('ix_resource_applications_created_at'), 'resource_applications', ['created_at'], unique=False)

    # 2. Credit Changes Table (Consistent naming)
    op.create_table(
        'credit_changes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('org_id', sa.Integer(), nullable=False),
        sa.Column('change_number', sa.String(length=64), nullable=False),
        sa.Column('target_user_id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='pending'),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
        sa.ForeignKeyConstraint(['target_user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    # Explicit business index requirements: Unique business number per Org
    op.create_index('uq_org_credit_change_num', 'credit_changes', ['org_id', 'change_number'], unique=True)
    # Performance indexes for status and time-based queries
    op.create_index(op.f('ix_credit_changes_status'), 'credit_changes', ['status'], unique=False)
    op.create_index(op.f('ix_credit_changes_created_at'), 'credit_changes', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_table('credit_changes')
    op.drop_table('resource_applications')
