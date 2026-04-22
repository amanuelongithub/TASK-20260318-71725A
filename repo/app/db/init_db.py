from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models.entities import Role, RolePermission, RoleType

def init_db(db: Session | None = None) -> None:
    if db is None:
        Base.metadata.create_all(bind=engine)
        db = SessionLocal()
        should_close = True
    else:
        should_close = False
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
                ("hospital", "create"),
                ("hospital", "update"),
                ("files", "read"),
                ("files", "write"),
                ("org", "read"),
                ("org", "update"),
                ("membership", "write"),
                ("dictionary", "read"),
            ],
            RoleType.REVIEWER: [("process", "approve"), ("metrics", "read"), ("hospital", "read"), ("hospital", "create"), ("hospital", "update"), ("files", "read"), ("dictionary", "read")],
            RoleType.GENERAL_USER: [("process", "create"), ("metrics", "read"), ("hospital", "read"), ("hospital", "create"), ("hospital", "update"), ("files", "read"), ("files", "write"), ("dictionary", "read")],
            RoleType.AUDITOR: [
                ("audit", "read"),
                ("metrics", "read"),
                ("hospital", "read"),
                ("data_governance", "read"),
                ("export", "read"),
                ("files", "read"),
                ("dictionary", "read"),
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
                "name": "Credit Change Flow",
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
            if not db.scalar(select(ProcessDefinition).where(ProcessDefinition.name == ex["name"], ProcessDefinition.org_id == 1)):
                db.add(ProcessDefinition(org_id=1, name=ex["name"], definition=ex["definition"]))
        db.commit()

        # Seed Data Dictionary
        from app.models.entities import DataDictionaryEntry
        dictionary_data = [
            ("User", "username", "Unique identifying name for login", "String", "Medium"),
            ("User", "email_encrypted", "Contact email address (stored encrypted)", "LargeBinary", "High"),
            ("Patient", "patient_number_encrypted", "Unique medical record number (MRN) - Encrpyted", "LargeBinary", "High"),
            ("Patient", "patient_number_hash", "Blind index for searching patient number", "String", "Medium"),
            ("Patient", "full_name", "Legal name of the patient", "String", "High"),
            ("Doctor", "license_number_encrypted", "Professional license ID - Encrypted", "LargeBinary", "High"),
            ("Doctor", "license_number_hash", "Blind index for searching license number", "String", "Medium"),
            ("Doctor", "full_name", "Name of the doctor", "String", "Low"),
            ("Appointment", "appointment_number", "Business ID for the encounter", "String", "Low"),
            ("Appointment", "status", "Current state of the appointment workflow", "String", "Low"),
            ("Expense", "expense_number", "Business ID for the expense claim", "String", "Low"),
            ("Expense", "amount", "Monetary value of the claim", "Float", "Medium"),
            ("AuditLog", "event", "Type of action performed", "String", "Low"),
            ("AuditLog", "event_metadata", "Contextual details of the action", "JSON", "Medium"),
            ("ResourceApplication", "application_number", "Business ID for the resource request", "String", "Low"),
            ("CreditChange", "change_number", "Business ID for the credit line update", "String", "Low"),
        ]
        for entity, field, desc, ftype, sens in dictionary_data:
            if not db.scalar(select(DataDictionaryEntry).where(DataDictionaryEntry.entity == entity, DataDictionaryEntry.field_name == field)):
                db.add(DataDictionaryEntry(
                    entity=entity, field_name=field, description=desc, 
                    field_type=ftype, sensitivity=sens
                ))
        db.commit()
    finally:
        if should_close:
            db.close()


if __name__ == "__main__":
    init_db()
