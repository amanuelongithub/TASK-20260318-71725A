"""business id idempotency

Revision ID: 20260422_02
Revises: 20260422_01
Create Date: 2026-04-22 00:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260422_02'
down_revision = '20260422_01'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add unique constraint for (org_id, business_id) on process_instances
    op.create_unique_constraint('uq_org_business_id', 'process_instances', ['org_id', 'business_id'])


def downgrade() -> None:
    op.drop_constraint('uq_org_business_id', 'process_instances', type_='unique')
