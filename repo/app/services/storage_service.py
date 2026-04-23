from datetime import datetime
from pathlib import Path

from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import file_sha256
from app.models.entities import Attachment, User
from app.services.audit_service import log_event


ALLOWED_MIME_TYPES = {"application/pdf", "image/png", "image/jpeg", "application/json"}

def _validate_content_signature(content: bytes, mime_type: str) -> bool:
    """Basic magic number validation as required by compliance."""
    mime_type = mime_type.lower()
    if mime_type == "application/pdf":
        return content.startswith(b"%PDF-")
    if mime_type == "image/png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if mime_type == "image/jpeg":
        return content.startswith(b"\xff\xd8\xff")
    if mime_type == "application/json":
        # Support UTF-8 BOM
        if content.startswith(b"\xef\xbb\xbf"):
            content = content[3:]
        stripped = content.lstrip()
        # Broaden validation to allow objects, arrays, strings, numbers, etc.
        # Valid JSON starts with one of: { [ " t f n or -0123456789
        if not stripped:
            return False
        first_char = stripped[0:1]
        return first_char in b"{[\"tfn" or first_char in b"-0123456789"
    return False


async def save_attachment(
    db: Session, 
    actor: User, 
    upload: UploadFile, 
    business_owner_id: str | None = None,
    task_id: int | None = None,
    process_instance_id: int | None = None,
    entity_type: str | None = None
) -> dict:
    content_type = upload.content_type.lower() if upload.content_type else ""
    if content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=400, detail="Invalid file format. Allowed: PDF, PNG, JPEG, JSON.")


    # Validate business owner if provided
    if business_owner_id:
        # Check if the business entity exists and belongs to the actor's organization
        # Generic check for common entity types based on prefixes
        from app.models.entities import Expense, Appointment, ProcessInstance, ResourceApplication, CreditChange
        is_valid = False
        if business_owner_id.startswith("EXP-"):
            is_valid = db.scalar(select(Expense).where(Expense.expense_number == business_owner_id, Expense.org_id == actor.org_id)) is not None
        elif business_owner_id.startswith("APT-"):
            is_valid = db.scalar(select(Appointment).where(Appointment.appointment_number == business_owner_id, Appointment.org_id == actor.org_id)) is not None
        elif business_owner_id.startswith("RES-"):
            is_valid = db.scalar(select(ResourceApplication).where(ResourceApplication.application_number == business_owner_id, ResourceApplication.org_id == actor.org_id)) is not None
        elif business_owner_id.startswith("CRD-"):
            is_valid = db.scalar(select(CreditChange).where(CreditChange.change_number == business_owner_id, CreditChange.org_id == actor.org_id)) is not None
        elif business_owner_id.startswith("PROC-") or business_owner_id.isdigit():
             is_valid = db.scalar(select(ProcessInstance).where(ProcessInstance.business_id == business_owner_id, ProcessInstance.org_id == actor.org_id)) is not None
        
        if not is_valid:
            # If we can't find it with prefixes, just do a generic check or fail for safety
            # The audit suggests strictly validating this.
            raise HTTPException(status_code=403, detail="Invalid or unauthorized business entity ID")

    # Validate task_id and process_instance_id linkage and organization ownership
    from app.models.entities import Task, ProcessInstance
    if task_id:
        task = db.scalar(select(Task).where(Task.id == task_id, Task.org_id == actor.org_id))
        if not task:
            raise HTTPException(status_code=404, detail="Task not found or unauthorized")
        
        if process_instance_id and process_instance_id != task.process_instance_id:
            raise HTTPException(status_code=400, detail="Inconsistent linkage: task_id does not belong to the provided process_instance_id")
        
        process_instance_id = task.process_instance_id

    if process_instance_id:
        instance = db.scalar(select(ProcessInstance).where(ProcessInstance.id == process_instance_id, ProcessInstance.org_id == actor.org_id))
        if not instance:
            raise HTTPException(status_code=404, detail="Process instance not found or unauthorized")
        
        # Verify cross-linkage if business_owner_id is also provided
        if business_owner_id:
            if (business_owner_id.startswith("PROC-") or business_owner_id.isdigit()) and instance.business_id != business_owner_id:
                raise HTTPException(status_code=400, detail="Inconsistent linkage: process_instance_id does not match business_owner_id")

    content = await upload.read()
    # Reset read pointer for potential re-read or storage
    await upload.seek(0)
    
    max_bytes = settings.max_file_size_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(status_code=400, detail=f"File exceeds {settings.max_file_size_mb}MB")

    fingerprint = file_sha256(content)
    
    # CONTENT-BASED VALIDATION (MAGIC NUMBERS)
    if not _validate_content_signature(content, content_type):
         log_event(db, actor.org_id, actor.id, "file.signature_validation_failed", {"filename": upload.filename, "mime": content_type})

         db.commit()
         raise HTTPException(status_code=400, detail="File content does not match the declared format.")
    
    # REVISED Traceability Logic:
    # 1. Reuse disk storage path if content exists (Disk Deduplication)
    existing_file = db.scalar(select(Attachment).where(Attachment.sha256 == fingerprint).limit(1))
    if existing_file and Path(existing_file.storage_path).exists():
        file_path = Path(existing_file.storage_path)
        deduplicated = True
    else:
        storage = Path(settings.file_storage_path)
        storage.mkdir(parents=True, exist_ok=True)
        file_path = storage / f"{fingerprint}_{upload.filename}"
        file_path.write_bytes(content)
        deduplicated = False

    # 2. ALWAYS create a new DB record for this specific upload/link (Traceability)
    row = Attachment(
        org_id=actor.org_id,
        uploader_id=actor.id,
        filename=upload.filename,
        file_size=len(content),
        sha256=fingerprint,
        storage_path=str(file_path),
        business_owner_id=business_owner_id,
        task_id=task_id,
        process_instance_id=process_instance_id
    )
    db.add(row)
    db.flush() # Ensure row.id is populated for audit and traceability link
    
    # NEW: Wire to Data Governance Lifecycle for JSON batches
    validation_status = "not_applicable"
    if content_type == "application/json" and (upload.filename.startswith("batch") or business_owner_id is not None):

        import json
        from app.models.entities import ImportBatch
        from app.services import data_governance_service
        
        try:
            data = json.loads(content)
            records = []
            if isinstance(data, list):
                records = data
            elif isinstance(data, dict) and "records" in data:
                records = data["records"]
                
            if records:
                batch_id = f"BATCH-{fingerprint[:8]}-{datetime.utcnow().strftime('%H%M%S')}"
                batch = ImportBatch(
                    org_id=actor.org_id,
                    batch_id=batch_id,
                    source_name=upload.filename,
                    status="uploaded"
                )
                db.add(batch)
                db.commit() # Commit to ensure batch exists for validation service
                
                # Derive entity_type if not provided
                if not entity_type and business_owner_id:
                    if business_owner_id.startswith("EXP-"): entity_type = "expense"
                    elif business_owner_id.startswith("APT-"): entity_type = "appointment"
                    elif business_owner_id.startswith("RES-"): entity_type = "resource_application"
                    elif business_owner_id.startswith("CRD-"): entity_type = "credit_change"
                    elif business_owner_id.startswith("PAT-"): entity_type = "patient"
                    elif business_owner_id.startswith("DOC-"): entity_type = "doctor"
                
                allowed_existing_business_ids: set[str] = set()
                if business_owner_id:
                    allowed_existing_business_ids.add(business_owner_id.strip())

                result = data_governance_service.validate_records(
                    db,
                    actor,
                    batch_id,
                    records,
                    entity_type=entity_type or "unknown",
                    allowed_existing_business_ids=allowed_existing_business_ids,
                )
                validation_status = result["status"]
        except Exception as e:
            # We don't want to fail the whole upload if validation fails due to format, 
            # but we should log it.
            validation_status = f"error: {str(e)}"

    log_event(db, actor.org_id, actor.id, "file.uploaded", {"attachment_id": row.id, "filename": row.filename, "sha256": row.sha256})
    db.commit()
    db.refresh(row)
    return {
        "attachment_id": row.id,
        "sha256": row.sha256,
        "deduplicated": deduplicated,
        "validation_status": validation_status
    }


def get_attachment(db: Session, actor: User, attachment_id: int) -> Attachment:
    row = db.scalar(select(Attachment).where(Attachment.id == attachment_id, Attachment.org_id == actor.org_id))
    if not row:
        raise HTTPException(status_code=404, detail="Attachment not found")
        
    from app.models.entities import RoleType, Task, ProcessInstance
    
    # 1. Uploader always has access
    if row.uploader_id == actor.id:
        return row
        
    # 2. Business Ownership Verification (Required for all roles within organization)
    # This prevents AUDITORs and ADMINs from accessing unrelated sensitive files without a business reason.
    
    is_authorized = False
    access_reason = "general"

    if row.business_owner_id:
        # Check if it's a ProcessInstance
        instance = db.scalar(select(ProcessInstance).where(ProcessInstance.business_id == row.business_owner_id, ProcessInstance.org_id == actor.org_id))
        if instance:
            # Check if actor is initiator or has a task in this process
            has_task = db.scalar(select(Task).where(Task.process_instance_id == instance.id, Task.assignee_id == actor.id))
            if has_task or instance.initiator_id == actor.id:
                 is_authorized = True
                 access_reason = "process_participant"
            
            # Special case for ADMIN/AUDITOR: if it's an active process in their org, they can view it
            elif actor.role.name in {RoleType.ADMIN, RoleType.AUDITOR}:
                 is_authorized = True
                 access_reason = f"{actor.role.name.value}_oversight"

        if not is_authorized:
            # Check if it's an Appointment
            from app.models.entities import Appointment, Patient, Doctor
            appt = db.scalar(select(Appointment).where(Appointment.appointment_number == row.business_owner_id, Appointment.org_id == actor.org_id))
            if appt:
                patient = db.scalar(select(Patient).where(Patient.id == appt.patient_id))
                doctor = db.scalar(select(Doctor).where(Doctor.id == appt.doctor_id))
                if (patient and patient.user_id == actor.id) or (doctor and doctor.user_id == actor.id):
                    is_authorized = True
                    access_reason = "appointment_participant"
                elif actor.role.name in {RoleType.ADMIN, RoleType.AUDITOR}:
                    is_authorized = True
                    access_reason = f"{actor.role.name.value}_oversight"
            
        if not is_authorized:
            # Check if it's an Expense
            from app.models.entities import Expense
            expense = db.scalar(select(Expense).where(Expense.expense_number == row.business_owner_id, Expense.org_id == actor.org_id))
            if expense:
                if expense.submitted_by == actor.id:
                    is_authorized = True
                    access_reason = "expense_owner"
                elif actor.role.name in {RoleType.ADMIN, RoleType.AUDITOR}:
                    is_authorized = True
                    access_reason = f"{actor.role.name.value}_oversight"

        if not is_authorized:
            # Check if it's a ResourceApplication
            from app.models.entities import ResourceApplication
            res_app = db.scalar(select(ResourceApplication).where(ResourceApplication.application_number == row.business_owner_id, ResourceApplication.org_id == actor.org_id))
            if res_app:
                if res_app.applicant_id == actor.id:
                    is_authorized = True
                    access_reason = "resource_applicant"
                elif actor.role.name in {RoleType.ADMIN, RoleType.AUDITOR}:
                    is_authorized = True
                    access_reason = f"{actor.role.name.value}_oversight"

        if not is_authorized:
            # Check if it's a CreditChange
            from app.models.entities import CreditChange
            crd_change = db.scalar(select(CreditChange).where(CreditChange.change_number == row.business_owner_id, CreditChange.org_id == actor.org_id))
            if crd_change:
                if crd_change.target_user_id == actor.id:
                    is_authorized = True
                    access_reason = "credit_target"
                elif actor.role.name in {RoleType.ADMIN, RoleType.AUDITOR}:
                    is_authorized = True
                    access_reason = f"{actor.role.name.value}_oversight"

    if is_authorized:
        if actor.role.name in {RoleType.ADMIN, RoleType.AUDITOR}:
            from app.services.audit_service import log_event
            log_event(db, actor.org_id, actor.id, f"file.{actor.role.name.value}_read", {"attachment_id": row.id, "reason": access_reason})
        return row

    raise HTTPException(
        status_code=403, 
        detail="Access denied. You do not have ownership or a business-related permission to view this attachment, or you are bypassing validation checks."
    )



def list_attachments(db: Session, actor: User) -> list[Attachment]:
    return db.scalars(
        select(Attachment).where(Attachment.org_id == actor.org_id, Attachment.uploader_id == actor.id)
    ).all()
