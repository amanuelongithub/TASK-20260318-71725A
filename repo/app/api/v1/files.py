from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.middleware.auth import get_current_user, require_permission
from app.models.entities import User
from app.services import storage_service

router = APIRouter()


from fastapi import Form
from typing import Optional

@router.post("/upload")
async def upload_file(
    upload: UploadFile = File(...),
    business_owner_id: Optional[str] = Form(None),
    task_id: Optional[int] = Form(None),
    process_instance_id: Optional[int] = Form(None),
    entity_type: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("files", "write")),
) -> dict:
    return await storage_service.save_attachment(
        db, 
        actor, 
        upload, 
        business_owner_id=business_owner_id,
        task_id=task_id,
        process_instance_id=process_instance_id,
        entity_type=entity_type
    )


@router.get("/my")
def list_my_attachments(
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("files", "read")),
) -> list:
    rows = storage_service.list_attachments(db, actor)
    return [
        {
            "id": r.id,
            "filename": r.filename,
            "size": r.file_size,
            "sha256": r.sha256,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@router.get("/{attachment_id}")
def download_file(
    attachment_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("files", "read")),
) -> FileResponse:
    row = storage_service.get_attachment(db, actor, attachment_id)
    return FileResponse(row.storage_path, filename=row.filename)
