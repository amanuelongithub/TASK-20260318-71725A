"""merge heads

Revision ID: 20260422_08
Revises: 20260422_05, 20260422_06, 20260422_07
Create Date: 2026-04-22 10:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260422_08'
down_revision = ('20260422_05', '20260422_06', '20260422_07')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
