from datetime import datetime
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entities import DataValidationIssue, DataVersion, User, ImportBatchDetail, ImportBatch
from app.services.audit_service import log_event


def create_data_version(db: Session, actor: User, entity_type: str, entity_id: str, payload: dict) -> DataVersion:
    latest = db.scalar(
        select(func.max(DataVersion.version_no)).where(
            DataVersion.org_id == actor.org_id,
            DataVersion.entity_type == entity_type,
            DataVersion.entity_id == entity_id,
        )
    )
    version = DataVersion(
        org_id=actor.org_id,
        entity_type=entity_type,
        entity_id=entity_id,
        version_no=(latest or 0) + 1,
        payload=payload,
        created_by=actor.id,
    )
    db.add(version)
    log_event(db, actor.org_id, actor.id, "governance.version_created", {"entity_type": entity_type, "entity_id": entity_id, "version_no": version.version_no})
    db.flush()
    db.refresh(version)
    return version



# Configurable validation rules
DEFAULT_VALIDATION_RULES = {
    "required_fields": ["name", "amount"],
    "ranges": {
        "score": {"min": 0, "max": 100},
        "amount": {"min": 0}
    },
    "types": {
        "amount": float,
        "score": int
    }
}

def validate_records(db: Session, actor: User, batch_id: str, records: list[dict], rules: dict | None = None) -> dict:
    active_rules = rules or DEFAULT_VALIDATION_RULES
    issues: list[DataValidationIssue] = []
    seen_keys: set[str] = set()
    details: list[ImportBatchDetail] = []
    
    for idx, row in enumerate(records):
        record_id = str(row.get("id", idx))
        row_issues = []
        
        # 1. Required fields check
        for req_field in active_rules.get("required_fields", []):
            if req_field not in row or row[req_field] is None:
                row_issues.append({"issue": "missing_data", "field": req_field})
                issues.append(
                    DataValidationIssue(
                        org_id=actor.org_id,
                        batch_id=batch_id,
                        issue_type="missing_data",
                        severity="high",
                        field_name=req_field,
                        message=f"Missing required field: {req_field}",
                        record_ref=record_id,
                    )
                )

        # 2. Duplicate check
        if record_id in seen_keys:
            row_issues.append({"issue": "duplicate", "field": "id"})
            issues.append(
                DataValidationIssue(
                    org_id=actor.org_id,
                    batch_id=batch_id,
                    issue_type="duplicate",
                    severity="high",
                    field_name="id",
                    message="Duplicate record reference in batch",
                    record_ref=record_id,
                )
            )
        seen_keys.add(record_id)

        # 3. Range checks
        ranges = active_rules.get("ranges", {})
        for field, limits in ranges.items():
            if field in row:
                try:
                    val = float(row[field])
                    if "min" in limits and val < limits["min"]:
                        row_issues.append({"issue": "out_of_range_min", "field": field})
                    if "max" in limits and val > limits["max"]:
                        row_issues.append({"issue": "out_of_range_max", "field": field})
                except (ValueError, TypeError):
                    row_issues.append({"issue": "invalid_type", "field": field})

        # Record issues for each record
        if row_issues:
            for ri in row_issues:
                # Add to granular issues if not already added by range check
                if ri["issue"] not in {"missing_data", "duplicate"}:
                    issues.append(
                        DataValidationIssue(
                            org_id=actor.org_id,
                            batch_id=batch_id,
                            issue_type=ri["issue"],
                            severity="medium",
                            field_name=ri["field"],
                            message=f"Validation failed: {ri['issue']}",
                            record_ref=record_id,
                        )
                    )
            
        status = "failed" if row_issues else "success"
        details.append(
            ImportBatchDetail(
                org_id=actor.org_id,
                batch_id=batch_id,
                record_ref=record_id,
                status=status,
                issues={"errors": row_issues} if row_issues else None,
            )
        )

    for issue in issues:
        db.add(issue)
    for detail in details:
        db.add(detail)
        
    # Wire to ImportBatch lifecycle
    from app.models.entities import ImportBatch
    batch = db.scalar(select(ImportBatch).where(ImportBatch.batch_id == batch_id, ImportBatch.org_id == actor.org_id))
    if batch:
        success_count = sum(1 for d in details if d.status == "success")
        error_count = len(details) - success_count
        batch.status = "validated" if error_count == 0 else "failed"
        batch.stats = {
            "total_records": len(details),
            "success_count": success_count,
            "error_count": error_count,
            "validation_timestamp": datetime.utcnow().isoformat()
        }
        db.add(batch)
        log_event(db, actor.org_id, actor.id, "governance.batch_validated", {"batch_id": batch_id, "status": batch.status, "stats": batch.stats})


    db.commit()
    return {"batch_id": batch_id, "issue_count": len(issues), "status": batch.status if batch else "unknown"}


def rollback_to_version(db: Session, actor: User, version_id: int) -> dict:
    version = db.scalar(select(DataVersion).where(DataVersion.id == version_id, DataVersion.org_id == actor.org_id))
    if version is None:
        raise HTTPException(status_code=404, detail="Version not found")
        
    # Transactional restore
    payload = version.payload
    restored = False
    if version.entity_type == "expense":
        from app.models.entities import Expense
        entity = db.scalar(select(Expense).where(Expense.expense_number == version.entity_id, Expense.org_id == actor.org_id))
        if entity:
            for field in ["amount", "category", "status", "notes"]:
                if field in payload:
                    setattr(entity, field, payload[field])
            restored = True
    elif version.entity_type == "appointment":
        from app.models.entities import Appointment
        entity = db.scalar(select(Appointment).where(Appointment.appointment_number == version.entity_id, Appointment.org_id == actor.org_id))
        if entity:
            for field in ["status", "scheduled_time", "notes"]:
                if field in payload:
                    val = payload[field]
                    if field == "scheduled_time" and val:
                        val = datetime.fromisoformat(val)
                    setattr(entity, field, val)
            restored = True
    elif version.entity_type == "patient":
        from app.models.entities import Patient
        entity = db.scalar(select(Patient).where(Patient.id == int(version.entity_id), Patient.org_id == actor.org_id))
        if entity:
            for field in ["full_name", "dob"]:
                if field in payload:
                    val = payload[field]
                    if field == "dob" and val:
                        val = datetime.fromisoformat(val)
                    setattr(entity, field, val)
            restored = True
    elif version.entity_type == "doctor":
        from app.models.entities import Doctor
        entity = db.scalar(select(Doctor).where(Doctor.id == int(version.entity_id), Doctor.org_id == actor.org_id))
        if entity:
            for field in ["full_name", "specialty", "is_active"]:
                if field in payload:
                    setattr(entity, field, payload[field])
            restored = True

    if restored:
        # Create a new lineage record to track the rollback
        create_data_version(db, actor, version.entity_type, version.entity_id, payload)
        log_event(db, actor.org_id, actor.id, "governance.rollback_performed", {"entity_type": version.entity_type, "entity_id": version.entity_id, "version_id": version_id})
        db.commit()

    return {
        "status": "restored" if restored else "failed",
        "entity_type": version.entity_type,
        "entity_id": version.entity_id,
        "version_no": version.version_no,
        "payload": payload,
    }


def list_lineage(db: Session, actor: User, entity_type: str, entity_id: str) -> list[DataVersion]:
    return db.scalars(
        select(DataVersion).where(
            DataVersion.org_id == actor.org_id,
            DataVersion.entity_type == entity_type,
            DataVersion.entity_id == entity_id,
        ).order_by(DataVersion.version_no.desc())
    ).all()
