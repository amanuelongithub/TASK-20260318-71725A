"""global username uniqueness"""

from alembic import op
import sqlalchemy as sa

revision = "20260421_04"
down_revision = "20260421_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_username ON users (username)")
    else:
        op.drop_constraint("uq_username_org", "users", type_="unique")
        op.create_unique_constraint("uq_users_username", "users", ["username"])


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute("DROP INDEX IF EXISTS uq_users_username")
    else:
        op.drop_constraint("uq_users_username", "users", type_="unique")
        op.create_unique_constraint("uq_username_org", "users", ["username", "org_id"])
