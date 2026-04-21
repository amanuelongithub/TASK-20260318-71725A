import csv
from pathlib import Path

from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decrypt_field
from app.models.entities import RoleType, User


def _mask_value(field: str, value: str | None) -> str:
    if value is None:
        return ""
    if field == "full_name":
        return value[0] + "*" * (len(value) - 1) if len(value) > 1 else "*"
    if field == "email":
        if "@" not in value:
            return "***"
        name, domain = value.split("@", 1)
        return (name[:1] + "***@" + domain) if name else "***@" + domain
    if field == "username":
        return value[:2] + "***" if len(value) > 2 else "***"
    return value


def build_export_plan(requested_fields: list[str], role_name: str, requested_desensitize: bool) -> tuple[list[str], bool]:
    allowed = {"username", "full_name", "org_id", "created_at", "email"}
    fields = [f for f in requested_fields if f in allowed]
    if role_name != RoleType.ADMIN.value:
        fields = [f for f in fields if f != "email"]
    desensitize = requested_desensitize or role_name != RoleType.ADMIN.value
    return fields, desensitize


def _collect_rows(db: Session, org_id: int, columns: list[str], desensitize: bool) -> list[dict[str, str]]:
    users = db.scalars(select(User).where(User.org_id == org_id).order_by(User.id.asc())).all()
    rows: list[dict[str, str]] = []
    for user in users:
        row: dict[str, str] = {}
        for column in columns:
            if column == "email":
                raw = decrypt_field(user.email_encrypted) if user.email_encrypted else ""
            else:
                raw = getattr(user, column, "")
            text = str(raw) if raw is not None else ""
            row[column] = _mask_value(column, text) if desensitize else text
        rows.append(row)
    return rows


def generate_user_export_csv(db: Session, org_id: int, columns: list[str], output_path: Path, desensitize: bool) -> None:
    rows = _collect_rows(db, org_id, columns, desensitize)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def generate_user_export_xlsx(db: Session, org_id: int, columns: list[str], output_path: Path, desensitize: bool) -> None:
    rows = _collect_rows(db, org_id, columns, desensitize)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "users"
    ws.append(columns)
    for row in rows:
        ws.append([row.get(col, "") for col in columns])
    wb.save(output_path)
