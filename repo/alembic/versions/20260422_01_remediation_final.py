"""remediation final

Revision ID: 20260422_01
Revises: 8aa4006e3ed0
Create Date: 2026-04-22 00:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260422_01'
down_revision = '8aa4006e3ed0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    dialect = op.get_bind().dialect.name

    # 1. Create token_blacklist
    op.create_table(
        'token_blacklist',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('token_jti', sa.String(length=255), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_token_blacklist_token_jti'), 'token_blacklist', ['token_jti'], unique=True)
    op.create_index(op.f('ix_token_blacklist_expires_at'), 'token_blacklist', ['expires_at'], unique=False)

    # 2. Create organization_memberships
    op.create_table(
        'organization_memberships',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('org_id', sa.Integer(), nullable=False),
        sa.Column('role_id', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('joined_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'org_id', name='uq_user_org')
    )
    op.create_index(op.f('ix_organization_memberships_org_id'), 'organization_memberships', ['org_id'], unique=False)
    op.create_index(op.f('ix_organization_memberships_user_id'), 'organization_memberships', ['user_id'], unique=False)

    # 3. Update Patients
    op.add_column('patients', sa.Column('user_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_patients_user_id'), 'patients', ['user_id'], unique=False)
    if dialect != 'sqlite':
        op.create_foreign_key(op.f('patients_user_id_fkey'), 'patients', 'users', ['user_id'], ['id'])

    # 4. Update Doctors
    op.add_column('doctors', sa.Column('user_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_doctors_user_id'), 'doctors', ['user_id'], unique=False)
    if dialect != 'sqlite':
        op.create_foreign_key(op.f('doctors_user_id_fkey'), 'doctors', 'users', ['user_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint(op.f('doctors_user_id_fkey'), 'doctors', type_='foreignkey')
    op.drop_index(op.f('ix_doctors_user_id'), table_name='doctors')
    op.drop_column('doctors', 'user_id')
    
    op.drop_constraint(op.f('patients_user_id_fkey'), 'patients', type_='foreignkey')
    op.drop_index(op.f('ix_patients_user_id'), table_name='patients')
    op.drop_column('patients', 'user_id')
    
    op.drop_table('organization_memberships')
    op.drop_table('token_blacklist')
