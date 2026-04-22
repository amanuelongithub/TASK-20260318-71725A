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
    # REMOVED: Permanent unique constraint on (org_id, business_id) 
    # to support the prompt's 24-hour idempotency window requirement.
    # Service logic now handles the 24-hour check.
    pass


def downgrade() -> None:
    pass
