"""audit final pass

Revision ID: 20260422_04
Revises: 20260422_03
Create Date: 2026-04-22 02:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '20260422_04'
down_revision = '20260422_03'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add completed_at to process_instances
    op.add_column('process_instances', sa.Column('completed_at', sa.DateTime(), nullable=True))

    # 2. Add approved_at to expenses
    op.add_column('expenses', sa.Column('approved_at', sa.DateTime(), nullable=True))

    # 3. Add scheduled_at to appointments
    op.add_column('appointments', sa.Column('scheduled_at', sa.DateTime(), nullable=True))

    # 4. Create data_dictionary_entries
    op.create_table(
        'data_dictionary_entries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('entity', sa.String(length=64), nullable=False),
        sa.Column('field_name', sa.String(length=64), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('field_type', sa.String(length=64), nullable=False),
        sa.Column('sensitivity', sa.String(length=32), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_data_dictionary_entries_entity'), 'data_dictionary_entries', ['entity'], unique=False)
    op.create_index(op.f('ix_data_dictionary_entries_field_name'), 'data_dictionary_entries', ['field_name'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_data_dictionary_entries_field_name'), table_name='data_dictionary_entries')
    op.drop_index(op.f('ix_data_dictionary_entries_entity'), table_name='data_dictionary_entries')
    op.drop_table('data_dictionary_entries')
    op.drop_column('appointments', 'scheduled_at')
    op.drop_column('expenses', 'approved_at')
    op.drop_column('process_instances', 'completed_at')
