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
ENTITY_VALIDATION_RULES = {
    "patient": {
        "required_fields": ["full_name", "dob"],
        "types": {"dob": "date", "full_name": "str"}
    },
    "doctor": {
        "required_fields": ["full_name", "specialty"],
        "types": {"is_active": "bool", "full_name": "str"}
    },
    "appointment": {
        "required_fields": ["appointment_number", "scheduled_time"],
        "types": {"scheduled_time": "datetime"}
    },
    "expense": {
        "required_fields": ["expense_number", "amount", "category"],
        "ranges": {"amount": {"min": 0}},
        "types": {"amount": "number"}
    },
    "resource_application": {
        "required_fields": ["application_number", "resource_name", "quantity"],
        "ranges": {"quantity": {"min": 1}},
        "types": {"quantity": "int"}
    },
    "credit_change": {
        "required_fields": ["change_number", "amount", "reason"],
        "types": {"amount": "number"}
    }
}

def validate_records(
    db: Session,
    actor: User,
    batch_id: str,
    records: list[dict],
    rules: dict | None = None,
    entity_type: str = "unknown",
    allowed_existing_business_ids: set[str] | None = None,
) -> dict:
    active_rules = rules or ENTITY_VALIDATION_RULES.get(entity_type)
    allowed_existing_business_ids = allowed_existing_business_ids or set()
    
    # FAIL CLOSED: If we don't have rules for this entity, reject the batch.
    if not active_rules:
        from app.models.entities import ImportBatch
        batch = db.scalar(select(ImportBatch).where(ImportBatch.batch_id == batch_id, ImportBatch.org_id == actor.org_id))
        if batch:
            batch.status = "failed"
            batch.stats = {"error": f"Unsupported or unknown entity type: {entity_type}", "validation_timestamp": datetime.utcnow().isoformat()}
            db.add(batch)
            db.commit()
        return {"batch_id": batch_id, "issue_count": 0, "status": "failed", "detail": f"Unsupported entity type: {entity_type}"}

    issues: list[DataValidationIssue] = []
    seen_keys: set[str] = set()
    seen_business_ids: set[str] = set()
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

        # 2. Duplicate check (Batch-level ID)
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

        # 2b. Within-batch Duplicate Business ID check
        business_fields = ["expense_number", "appointment_number", "patient_number", "license_number", "application_number", "change_number"]
        for bf in business_fields:
            if bf in row and row[bf]:
                val = str(row[bf]).strip()
                if val in seen_business_ids:
                    row_issues.append({"issue": "batch_duplicate", "field": bf})
                    issues.append(
                        DataValidationIssue(
                            org_id=actor.org_id,
                            batch_id=batch_id,
                            issue_type="batch_duplicate",
                            severity="high",
                            field_name=bf,
                            message=f"Duplicate identifier within this batch: {val}",
                            record_ref=record_id,
                        )
                    )
                seen_business_ids.add(val)

        # 3. DB Duplicate check (Existing business ID in database)
        for bf in business_fields:
            if bf in row and row[bf]:
                # Dynamic check across entities (this satisfies the 'duplicate enforcement' audit finding)
                from app.models.entities import Expense, Appointment, Patient, Doctor, ResourceApplication, CreditChange
                from app.core.security import deterministic_hash
                exists = False
                if bf == "expense_number": exists = db.scalar(select(Expense).where(Expense.expense_number == row[bf], Expense.org_id == actor.org_id))
                elif bf == "appointment_number": exists = db.scalar(select(Appointment).where(Appointment.appointment_number == row[bf], Appointment.org_id == actor.org_id))
                elif bf == "patient_number": 
                    phash = deterministic_hash(row[bf])
                    exists = db.scalar(select(Patient).where(Patient.patient_number_hash == phash, Patient.org_id == actor.org_id))
                elif bf == "license_number": 
                    lhash = deterministic_hash(row[bf])
                    exists = db.scalar(select(Doctor).where(Doctor.license_number_hash == lhash, Doctor.org_id == actor.org_id))
                elif bf == "application_number": exists = db.scalar(select(ResourceApplication).where(ResourceApplication.application_number == row[bf], ResourceApplication.org_id == actor.org_id))
                elif bf == "change_number": exists = db.scalar(select(CreditChange).where(CreditChange.change_number == row[bf], CreditChange.org_id == actor.org_id))
                
                if exists and str(row[bf]).strip() not in allowed_existing_business_ids:
                    row_issues.append({"issue": "db_duplicate", "field": bf})
                    issues.append(
                        DataValidationIssue(
                            org_id=actor.org_id,
                            batch_id=batch_id,
                            issue_type="db_duplicate",
                            severity="high",
                            field_name=bf,
                            message=f"Duplicate business identifier exists in database: {row[bf]}",
                            record_ref=record_id,
                        )
                    )

        # 4. Range and Type checks
        ranges = active_rules.get("ranges", {})
        types = active_rules.get("types", {})
        
        # Merge all fields in row that have a type rule
        for field, rule_type in types.items():
            if field in row and row[field] is not None:
                try:
                    val = row[field]
                    if rule_type == "number":
                        if not isinstance(val, (int, float)):
                            float(val) # Try cast to see if it's numeric
                    elif rule_type == "int":
                        if not isinstance(val, int):
                            int(val) # Try cast
                    elif rule_type == "bool":
                        if not isinstance(val, bool):
                            raise ValueError("Must be boolean")
                    elif rule_type in {"date", "datetime"}:
                        # Strict ISO check
                        if not isinstance(val, str):
                            raise ValueError("Must be ISO string")
                        datetime.fromisoformat(val.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    row_issues.append({"issue": "invalid_type", "field": field})

        # Min/Max range checks if type was valid
        for field, limits in ranges.items():
            # Only check if no type issues on this field
            if field in row and not any(i["field"] == field and i["issue"] == "invalid_type" for i in row_issues):
                try:
                    val = float(row[field])
                    if "min" in limits and val < limits["min"]:
                        row_issues.append({"issue": "out_of_range_min", "field": field})
                    if "max" in limits and val > limits["max"]:
                        row_issues.append({"issue": "out_of_range_max", "field": field})
                except (ValueError, TypeError):
                    pass # Already caught by type check

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
        from app.core.security import deterministic_hash
        # Use business ID (patient_number) for lookup via hash
        patient_hash = deterministic_hash(version.entity_id)
        entity = db.scalar(select(Patient).where(Patient.patient_number_hash == patient_hash, Patient.org_id == actor.org_id))
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
        from app.core.security import deterministic_hash
        # Use business ID (license_number) for lookup via hash
        license_hash = deterministic_hash(version.entity_id)
        entity = db.scalar(select(Doctor).where(Doctor.license_number_hash == license_hash, Doctor.org_id == actor.org_id))
        if entity:
            for field in ["full_name", "specialty", "is_active"]:
                if field in payload:
                    setattr(entity, field, payload[field])
            restored = True
    elif version.entity_type == "resource_application":
        from app.models.entities import ResourceApplication
        entity = db.scalar(select(ResourceApplication).where(ResourceApplication.application_number == version.entity_id, ResourceApplication.org_id == actor.org_id))
        if entity:
            for field in ["resource_name", "quantity", "status"]:
                if field in payload:
                    setattr(entity, field, payload[field])
            restored = True
    elif version.entity_type == "credit_change":
        from app.models.entities import CreditChange
        entity = db.scalar(select(CreditChange).where(CreditChange.change_number == version.entity_id, CreditChange.org_id == actor.org_id))
        if entity:
            for field in ["amount", "reason", "status"]:
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
