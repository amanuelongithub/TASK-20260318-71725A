from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.middleware.auth import require_permission
from app.models.entities import ExportJob, User
from app.schemas.export import ExportJobCreateRequest
from app.services.audit_service import log_event
from app.services.export_service import build_export_plan
from app.tasks.jobs import process_export_job

router = APIRouter()
ALLOWED_EXPORT_FORMATS = {"csv", "xlsx"}


@router.post("/jobs")
def create_export_job(
    payload: ExportJobCreateRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("export", "create")),
) -> dict:
    role_name = actor.role.name.value if actor.role else ""
    sanitized, desensitize = build_export_plan(payload.fields, role_name, payload.desensitize)
    export_format = payload.format if payload.format in ALLOWED_EXPORT_FORMATS else "csv"
    job = ExportJob(
        org_id=actor.org_id,
        requested_by=actor.id,
        fields={"columns": sanitized, "desensitize": desensitize, "format": export_format},
        status="queued",
    )
    db.add(job)
    log_event(db, actor.org_id, actor.id, "export.job_created", {"fields": sanitized, "desensitize": desensitize, "format": export_format})
    db.commit()
    db.refresh(job)
    try:
        process_export_job.delay(job.id)
    except Exception:
        process_export_job.apply(args=[job.id])
    return {"job_id": job.id, "status": job.status, "fields": sanitized}


@router.get("/jobs/{job_id}")
def get_export_job(
    job_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("export", "read")),
) -> dict:
    job = db.scalar(select(ExportJob).where(ExportJob.id == job_id, ExportJob.org_id == actor.org_id))
    if job is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Export job not found")
        
    # Security: Hide internal output_path. 
    # Use a logical status and include a download URL if completed.
    response = {
        "job_id": job.id, 
        "status": job.status, 
        "fields": job.fields,
        "created_at": job.created_at
    }
    if job.status == "completed":
        response["download_url"] = f"/api/export/jobs/{job.id}/download"
        
    return response


@router.get("/jobs/{job_id}/download")
def download_export_file(
    job_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("export", "read")),
):
    job = db.scalar(select(ExportJob).where(ExportJob.id == job_id, ExportJob.org_id == actor.org_id))
    if job is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Export job not found")
    
    if job.status != "completed" or not job.output_path:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Export job is not completed or file is missing")
    
    import os
    if not os.path.exists(job.output_path):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Export file not found on disk")
    
    from fastapi.responses import FileResponse
    filename = os.path.basename(job.output_path)
    return FileResponse(
        path=job.output_path,
        filename=filename,
        media_type="application/octet-stream"
    )

