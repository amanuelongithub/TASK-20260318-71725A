import csv
from pathlib import Path

from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decrypt_field
from typing import Any
from app.models.entities import RoleType, User


from app.core.security import decrypt_field, mask_value
from app.models.entities import (
    RoleType, User, Patient, Doctor, Appointment, Expense, AuditLog
)


def _mask_column(field: str, value: Any) -> str:
    return mask_value(field, value)


def build_export_plan(entity_type: str, requested_fields: list[str], role_name: str, requested_desensitize: bool) -> tuple[list[str], bool]:
    whitelist = {
        "users": {"id", "username", "full_name", "org_id", "created_at", "email"},
        "patients": {"id", "patient_number", "full_name", "dob", "phone_number", "created_at"},
        "doctors": {"id", "license_number", "full_name", "specialty", "is_active", "created_at"},
        "appointments": {"id", "appointment_number", "patient_id", "doctor_id", "status", "scheduled_time", "created_at"},
        "expenses": {"id", "expense_number", "amount", "category", "status", "submitted_by", "created_at"},
        "audit_logs": {"id", "actor_id", "event", "event_metadata", "created_at"}
    }
    
    allowed = whitelist.get(entity_type, set())
    fields = [f for f in requested_fields if f in allowed]
    
    # Audit Rule: Non-admins cannot see raw sensitive numbers/emails
    sensitive = {"email", "patient_number", "license_number", "phone_number", "id_card_num"}
    if role_name != RoleType.ADMIN.value:
         desensitize = True
    else:
         desensitize = requested_desensitize
         
    return fields, desensitize


def _collect_rows(db: Session, org_id: int, entity_type: str, columns: list[str], desensitize: bool) -> list[dict[str, str]]:
    entity_map = {
        "users": User,
        "patients": Patient,
        "doctors": Doctor,
        "appointments": Appointment,
        "expenses": Expense,
        "audit_logs": AuditLog
    }
    
    model = entity_map.get(entity_type)
    if not model:
        return []
        
    records = db.scalars(select(model).where(model.org_id == org_id).order_by(model.id.asc())).all()
    rows: list[dict[str, str]] = []
    
    for rec in records:
        row: dict[str, str] = {}
        for column in columns:
            # Handle encrypted fields
            if column in {"email", "patient_number", "license_number", "phone_number", "id_card_num"}:
                encrypted_attr = f"{column}_encrypted"
                if hasattr(rec, encrypted_attr):
                    val = getattr(rec, encrypted_attr)
                    raw = decrypt_field(val) if val else ""
                else:
                    raw = getattr(rec, column, "")
            else:
                raw = getattr(rec, column, "")
                
            text = str(raw) if raw is not None else ""
            row[column] = _mask_column(column, text) if desensitize else text
        rows.append(row)
    return rows


def generate_export_csv(db: Session, org_id: int, entity_type: str, columns: list[str], output_path: Path, desensitize: bool) -> None:
    rows = _collect_rows(db, org_id, entity_type, columns, desensitize)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def generate_export_xlsx(db: Session, org_id: int, entity_type: str, columns: list[str], output_path: Path, desensitize: bool) -> None:
    rows = _collect_rows(db, org_id, entity_type, columns, desensitize)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = entity_type
    ws.append(columns)
    for row in rows:
        ws.append([row.get(col, "") for col in columns])
    wb.save(output_path)
