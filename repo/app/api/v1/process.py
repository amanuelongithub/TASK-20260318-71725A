from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.middleware.auth import require_permission
from app.models.entities import User
from app.schemas.process import CompleteTaskRequest, CreateProcessDefinitionRequest, ProcessInstanceOut, StartProcessRequest, TaskOut
from app.services import process_service

router = APIRouter()


@router.post("/definitions")
def create_definition(
    payload: CreateProcessDefinitionRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("process", "create")),
) -> dict:
    item = process_service.create_definition(db, actor, payload)
    return {"id": item.id, "name": item.name, "version": item.version}


@router.post("/instances", response_model=ProcessInstanceOut)
def start_instance(
    payload: StartProcessRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("process", "create")),
) -> ProcessInstanceOut:
    instance = process_service.start_process(
        db,
        actor,
        payload.process_definition_id,
        payload.business_id,
        payload.idempotency_key,
        payload.variables,
    )
    return ProcessInstanceOut(id=instance.id, status=instance.status.value, current_node=instance.current_node, sla_due_at=instance.sla_due_at)


@router.post("/tasks/{task_id}/complete")
def complete_task(
    task_id: int,
    payload: CompleteTaskRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("process", "approve")),
) -> dict:
    task = process_service.complete_task(db, actor, task_id, payload.decision, payload.comment)
    return {"task_id": task.id, "status": task.status.value}


@router.get("/tasks/me", response_model=list[TaskOut])
def my_tasks(
    skip: int = 0,
    limit: int = 10,
    status: str | None = None,
    node_key: str | None = None,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("process", "approve")),
) -> list[TaskOut]:
    rows = process_service.list_my_tasks(db, actor, skip, limit, status, node_key)
    return [
        TaskOut(
            id=row.id,
            process_instance_id=row.process_instance_id,
            node_key=row.node_key,
            status=row.status.value,
            sla_due_at=row.sla_due_at,
        )
        for row in rows
    ]


@router.get("/instances", response_model=list[ProcessInstanceOut])
def list_instances(
    skip: int = 0,
    limit: int = 10,
    status: str | None = None,
    business_id: str | None = None,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("process", "create")),
) -> list[ProcessInstanceOut]:
    rows = process_service.list_instances(db, actor, skip, limit, status, business_id)
    return [
        ProcessInstanceOut(
            id=row.id,
            status=row.status.value,
            current_node=row.current_node,
            sla_due_at=row.sla_due_at,
        )
        for row in rows
    ]
