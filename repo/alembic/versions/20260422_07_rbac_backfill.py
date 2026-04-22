"""rbac backfill

Revision ID: 20260422_07
Revises: 8aa4006e3ed0
Create Date: 2026-04-22 04:35:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '20260422_07'
down_revision = '8aa4006e3ed0'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Deterministic backfill of hospital:create and hospital:update permissions
    # 1. Get role IDs for relevant types
    conn = op.get_bind()
    roles = conn.execute(sa.text("SELECT id, name FROM roles")).fetchall()
    role_map = {r.name: r.id for r in roles}
    
    # Define grants (Resource, Action)
    grants = [("hospital", "create"), ("hospital", "update")]
    
    # Roles that should get these: ADMIN, REVIEWER, GENERAL_USER
    target_roles = ["administrator", "reviewer", "general_user"]
    
    for role_name in target_roles:
        role_id = role_map.get(role_name)
        if role_id:
            for res, act in grants:
                # Check if already exists to ensure idempotency
                exists = conn.execute(sa.text(
                    "SELECT 1 FROM role_permissions WHERE role_id = :r AND resource = :res AND action = :act"
                ), {"r": role_id, "res": res, "act": act}).fetchone()
                
                if not exists:
                    conn.execute(sa.text(
                        "INSERT INTO role_permissions (role_id, resource, action) VALUES (:r, :res, :act)"
                    ), {"r": role_id, "res": res, "act": act})

def downgrade() -> None:
    # Downgrade logic: remove the specific permissions added by this migration
    conn = op.get_bind()
    conn.execute(sa.text(
        "DELETE FROM role_permissions WHERE resource = 'hospital' AND action IN ('create', 'update')"
    ))
