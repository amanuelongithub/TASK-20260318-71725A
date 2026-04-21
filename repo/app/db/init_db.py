from sqlalchemy import select

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models.entities import Role, RolePermission, RoleType


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        for role_type in RoleType:
            if db.scalar(select(Role).where(Role.name == role_type)) is None:
                db.add(Role(name=role_type))
        db.commit()

        roles = {r.name: r for r in db.scalars(select(Role)).all()}
        mapping = {
            RoleType.ADMIN: [
                ("process", "create"),
                ("process", "approve"),
                ("metrics", "read"),
                ("audit", "read"),
                ("export", "create"),
                ("export", "read"),
                ("data_governance", "read"),
                ("data_governance", "write"),
                ("hospital", "read"),

                ("files", "read"),
                ("files", "write"),
            ],
            RoleType.REVIEWER: [("process", "approve"), ("metrics", "read"), ("hospital", "read"), ("files", "read")],
            RoleType.GENERAL_USER: [("process", "create"), ("metrics", "read"), ("hospital", "read"), ("files", "read"), ("files", "write")],
            RoleType.AUDITOR: [
                ("audit", "read"),
                ("metrics", "read"),
                ("hospital", "read"),
                ("data_governance", "read"),
                ("export", "read"),
                ("files", "read"),
            ],
        }

        for role_type, grants in mapping.items():
            role = roles[role_type]
            for resource, action in grants:
                exists = db.scalar(
                    select(RolePermission).where(
                        RolePermission.role_id == role.id,
                        RolePermission.resource == resource,
                        RolePermission.action == action,
                    )
                )
                if exists is None:
                    db.add(RolePermission(role_id=role.id, resource=resource, action=action))
        db.commit()

        # Ensure default organization exists
        from app.models import entities
        org = db.scalar(select(entities.Organization).where(entities.Organization.id == 1))
        if org is None:
            db.add(entities.Organization(id=1, org_code="DEFAULT", name="Default Organization"))
            db.commit()

        # Seed Workflow Examples
        from app.models.entities import ProcessDefinition
        examples = [
            {
                "name": "Resource Application Flow",
                "definition": {
                    "first_node": "submit",
                    "nodes": {
                        "submit": {"timeout_hours": 24},
                        "manager_review": {"timeout_hours": 48, "on_timeout": "escalate"},
                        "finance_approval": {"timeout_hours": 72, "join_strategy": "quorum", "quorum": 1}
                    },
                    "transitions": {
                        "submit": {"approve": "manager_review"},
                        "manager_review": {"approve": "finance_approval", "reject": "submit"},
                        "finance_approval": {"approve": "completed", "reject": "manager_review"}
                    },
                    "assignees": {
                        "manager_review": "role:reviewer",
                        "finance_approval": "role:administrator"
                    }
                }
            },
            {
                "name": "Credit Approval Flow",
                "definition": {
                    "first_node": "data_entry",
                    "nodes": {
                        "data_entry": {"timeout_hours": 12},
                        "risk_assessment": {"timeout_hours": 24},
                        "final_decision": {"timeout_hours": 48}
                    },
                    "transitions": {
                        "data_entry": {"approve": "risk_assessment"},
                        "risk_assessment": {
                            "branches": [
                                {"when": "var:risk_score=='low'", "next": "final_decision"},
                                {"when": "var:risk_score=='high'", "next": "rejected"}
                            ]
                        },
                        "final_decision": {"approve": "completed", "reject": "data_entry"}
                    },
                    "assignees": {
                        "risk_assessment": "role:reviewer",
                        "final_decision": "role:administrator"
                    }
                }
            }
        ]
        for ex in examples:
            if not db.scalar(select(ProcessDefinition).where(ProcessDefinition.name == ex["name"])):
                db.add(ProcessDefinition(org_id=1, name=ex["name"], definition=ex["definition"]))
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    init_db()
