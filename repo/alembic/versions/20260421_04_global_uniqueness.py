"""global username uniqueness"""

from alembic import op
import sqlalchemy as sa

revision = "20260421_04"
down_revision = "20260421_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Drop the old org-scoped uniqueness constraint
    # Note: name was uq_username_org from migration 01
    op.drop_constraint("uq_username_org", "users", type_="unique")

    # 2. Add global uniqueness constraint/index to username
    op.create_unique_constraint("uq_users_username", "users", ["username"])


def downgrade() -> None:
    op.drop_constraint("uq_users_username", "users", type_="unique")
    op.create_unique_constraint("uq_username_org", "users", ["username", "org_id"])
