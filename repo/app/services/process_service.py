from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models.entities import ProcessDefinition, ProcessInstance, ProcessStatus, Role, RoleType, Task, TaskStatus, User
from app.schemas.process import CreateProcessDefinitionRequest
from app.services.audit_service import log_event

def _perform_writeback(db: Session, business_id: str, new_status: str):
    from app.models.entities import Expense, Appointment, Patient, Doctor
    if not business_id: return
    if business_id.startswith("EXP-"):
        entity = db.scalar(select(Expense).where(Expense.expense_number == business_id))
        if entity:
            entity.status = new_status
    elif business_id.startswith("APT-"):
        entity = db.scalar(select(Appointment).where(Appointment.appointment_number == business_id))
        if entity:
            entity.status = new_status



def _condition_matches(condition: str | None, context: dict) -> bool:
    if not condition:
        return True
    normalized = condition.strip().lower()
    if normalized in {"always", "true"}:
        return True
    if normalized.startswith("decision=="):
        return context.get("decision", "").lower() == normalized.split("==", 1)[1].strip("'\" ")
    if normalized.startswith("var:"):
        key, _, expected = normalized[4:].partition("==")
        actual = str(context.get("variables", {}).get(key.strip(), "")).lower()
        return actual == expected.strip("'\" ").lower()
    return False


def _resolve_next_nodes(definition: dict, node_key: str, decision: str, variables: dict | None = None) -> list[str]:
    transitions = definition.get("transitions", {})
    node_rules = transitions.get(node_key, {})
    candidates = node_rules.get("branches", [])
    if candidates:
        for branch in candidates:
            if _condition_matches(branch.get("when"), {"decision": decision, "variables": variables or {}}):
                next_nodes = branch.get("next", [])
                return next_nodes if isinstance(next_nodes, list) else [next_nodes]
    mapped = node_rules.get(decision)
    if mapped is None:
        return []
    return mapped if isinstance(mapped, list) else [mapped]


def _resolve_assignees(db: Session, org_id: int, initiator_id: int, raw_assignees: list | int | str | None) -> list[int]:
    if raw_assignees is None:
        return [initiator_id]
    values = raw_assignees if isinstance(raw_assignees, list) else [raw_assignees]
    resolved: list[int] = []
    for item in values:
        if isinstance(item, int):
            resolved.append(item)
            continue
        text = str(item).strip()
        if text.isdigit():
            resolved.append(int(text))
            continue
        if text.startswith("role:"):
            role_name = text.split(":", 1)[1]
            try:
                role_enum = RoleType(role_name)
            except ValueError:
                role_enum = None
            role = db.scalar(select(Role).where(Role.name == role_enum)) if role_enum else None
            if role:
                users = db.scalars(select(User).where(User.org_id == org_id, User.role_id == role.id, User.is_active.is_(True))).all()
                resolved.extend([u.id for u in users])
    return list(dict.fromkeys(resolved)) or [initiator_id]


def _should_advance_from_node(db: Session, definition: dict, instance_id: int, node_key: str) -> bool:
    node_cfg = definition.get("nodes", {}).get(node_key, {})
    strategy = str(node_cfg.get("join_strategy", "wait_all")).lower()
    if strategy == "wait_any":
        return True
    if strategy == "quorum":
        threshold = int(node_cfg.get("quorum", 1))
        approved = db.scalar(
            select(func.count(Task.id)).where(
                Task.process_instance_id == instance_id,
                Task.node_key == node_key,
                Task.status == TaskStatus.APPROVED,
            )
        ) or 0
        return approved >= threshold
    pending = db.scalar(
        select(Task).where(
            Task.process_instance_id == instance_id,
            Task.node_key == node_key,
            Task.status == TaskStatus.PENDING,
        )
    )
    return pending is None


def create_definition(db: Session, actor: User, payload: CreateProcessDefinitionRequest) -> ProcessDefinition:
    item = ProcessDefinition(org_id=actor.org_id, name=payload.name, definition=payload.definition)
    db.add(item)
    log_event(db, actor.org_id, actor.id, "process.definition_created", {"name": payload.name})
    db.commit()
    db.refresh(item)
    return item


def start_process(
    db: Session,
    actor: User,
    process_definition_id: int,
    business_id: str,
    idempotency_key: str,
    variables: dict | None = None,
) -> ProcessInstance:
    # Idempotency check - DURABLY guaranteed by unique constraint on (org_id, business_id)
    # the 24-hour window is removed to ensure absolute uniqueness as per audit requirements.
    existing = db.scalar(
        select(ProcessInstance).where(
            and_(
                ProcessInstance.org_id == actor.org_id,
                ((ProcessInstance.idempotency_key == idempotency_key) | 
                 (ProcessInstance.business_id == business_id))
            )
        )
    )
    if existing:
        return existing

    definition = db.scalar(
        select(ProcessDefinition).where(
            ProcessDefinition.id == process_definition_id,
            ProcessDefinition.org_id == actor.org_id,
            ProcessDefinition.is_active.is_(True),
        )
    )
    if definition is None:
        raise HTTPException(status_code=404, detail="Process definition not found")

    first_node = definition.definition.get("first_node", "start")
    node_cfg = definition.definition.get("nodes", {}).get(first_node, {})
    timeout_hours = int(node_cfg.get("timeout_hours", 48))
    
    from sqlalchemy.exc import IntegrityError
    
    instance = ProcessInstance(
        org_id=actor.org_id,
        process_definition_id=process_definition_id,
        initiator_id=actor.id,
        status=ProcessStatus.RUNNING,
        current_node=first_node,
        business_id=business_id,
        idempotency_key=idempotency_key,
        variables=variables or {},
        sla_due_at=now + timedelta(hours=48), # Global SLA aligned to prompt
    )
    db.add(instance)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        # Fetch the existing instance that caused the conflict
        existing = db.scalar(
            select(ProcessInstance).where(
                and_(
                    ProcessInstance.org_id == actor.org_id,
                    ((ProcessInstance.idempotency_key == idempotency_key) | 
                     (ProcessInstance.business_id == business_id))
                )
            )
        )
        if existing:
            return existing
        raise # Rethrow if we can't find it for some reason
    raw_assignees = definition.definition.get("assignees", {}).get(first_node, [actor.id])
    assignees = _resolve_assignees(db, actor.org_id, actor.id, raw_assignees)
    due = now + timedelta(hours=timeout_hours)
    for assignee_id in assignees:
        db.add(
            Task(
                org_id=actor.org_id,
                process_instance_id=instance.id,
                assignee_id=int(assignee_id),
                node_key=first_node,
                status=TaskStatus.PENDING,
                sla_due_at=due,
            )
        )
    log_event(db, actor.org_id, actor.id, "process.started", {"instance_id": instance.id, "node": first_node, "assignees": assignees})
    db.commit()
    db.refresh(instance)
    return instance


def complete_task(db: Session, actor: User, task_id: int, decision: str, comment: str | None) -> Task:
    task = db.scalar(select(Task).where(Task.id == task_id, Task.org_id == actor.org_id))
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.assignee_id != actor.id:
        raise HTTPException(status_code=403, detail="Only assignee can complete task")
    if task.status != TaskStatus.PENDING:
        raise HTTPException(status_code=409, detail="Task already completed")

    instance = db.scalar(select(ProcessInstance).where(ProcessInstance.id == task.process_instance_id))
    if instance is None:
        raise HTTPException(status_code=404, detail="Process instance not found")

    normalized = decision.lower()
    if normalized not in {"approve", "reject"}:
        raise HTTPException(status_code=400, detail="Decision must be approve or reject")

    task.status = TaskStatus.APPROVED if normalized == "approve" else TaskStatus.REJECTED
    task.comment = comment
    task.completed_at = datetime.utcnow()
    definition = db.scalar(select(ProcessDefinition).where(ProcessDefinition.id == instance.process_definition_id))
    if definition is None:
        raise HTTPException(status_code=404, detail="Process definition not found")

    if normalized == "reject":
        sibling_tasks = db.scalars(
            select(Task).where(
                Task.process_instance_id == task.process_instance_id,
                Task.node_key == task.node_key,
                Task.status == TaskStatus.PENDING,
                Task.id != task.id,
            )
        ).all()
        for sibling in sibling_tasks:
            sibling.status = TaskStatus.REJECTED
            sibling.comment = "Auto-rejected due to peer rejection"
            sibling.completed_at = datetime.utcnow()
        instance.status = ProcessStatus.REJECTED
        instance.current_node = "rejected"
        _perform_writeback(db, instance.business_id, "rejected")
    else:
        should_advance = _should_advance_from_node(db, definition.definition, task.process_instance_id, task.node_key)
        if not should_advance:
            log_event(
                db,
                actor.org_id,
                actor.id,
                "process.task_waiting_parallel",
                {"task_id": task.id, "node_key": task.node_key, "instance_id": instance.id},
            )
            db.commit()
            db.refresh(task)
            return task
        sibling_tasks = db.scalars(
            select(Task).where(
                Task.process_instance_id == task.process_instance_id,
                Task.node_key == task.node_key,
                Task.status == TaskStatus.PENDING,
            )
        ).all()
        for sibling in sibling_tasks:
            sibling.status = TaskStatus.APPROVED
            sibling.comment = "Auto-completed by join strategy"
            sibling.completed_at = datetime.utcnow()

        next_nodes = _resolve_next_nodes(definition.definition, task.node_key, "approve", instance.variables)
        if next_nodes:
            instance.current_node = ",".join(next_nodes)
            assignees_map = definition.definition.get("assignees", {})
            nodes_cfg = definition.definition.get("nodes", {})
            for next_node in next_nodes:
                node_cfg = nodes_cfg.get(next_node, {})
                timeout_hours = int(node_cfg.get("timeout_hours", 48))
                due = datetime.utcnow() + timedelta(hours=timeout_hours)
                assignees = _resolve_assignees(
                    db,
                    actor.org_id,
                    instance.initiator_id,
                    assignees_map.get(next_node, [instance.initiator_id]),
                )
                for assignee_id in assignees:
                    db.add(
                        Task(
                            org_id=actor.org_id,
                            process_instance_id=instance.id,
                            assignee_id=int(assignee_id),
                            node_key=next_node,
                            status=TaskStatus.PENDING,
                            sla_due_at=due,
                        )
                    )
        else:
            instance.status = ProcessStatus.COMPLETED
            instance.current_node = "completed"
            _perform_writeback(db, instance.business_id, "approved")

    log_event(db, actor.org_id, actor.id, "process.task_completed", {"task_id": task_id, "decision": normalized, "instance_id": instance.id})
    db.commit()
    db.refresh(task)
    return task


def list_my_tasks(
    db: Session, actor: User, skip: int = 0, limit: int = 10, status: str | None = None, node_key: str | None = None
) -> list[Task]:
    query = select(Task).where(Task.org_id == actor.org_id, Task.assignee_id == actor.id)
    if status:
        vals = [v.strip() for v in status.split(",") if v.strip()]
        if len(vals) == 1:
            query = query.where(Task.status == vals[0])
        elif len(vals) > 1:
            query = query.where(Task.status.in_(vals))
            
    if node_key:
        vals = [v.strip() for v in node_key.split(",") if v.strip()]
        if len(vals) == 1:
            query = query.where(Task.node_key == vals[0])
        elif len(vals) > 1:
            query = query.where(Task.node_key.in_(vals))
            
    return db.scalars(query.offset(skip).limit(limit)).all()


def list_instances(
    db: Session, actor: User, skip: int = 0, limit: int = 10, status: str | None = None, business_id: str | None = None
) -> list[ProcessInstance]:
    query = select(ProcessInstance).where(ProcessInstance.org_id == actor.org_id)
    if status:
        vals = [v.strip() for v in status.split(",") if v.strip()]
        if len(vals) == 1:
            query = query.where(ProcessInstance.status == vals[0])
        elif len(vals) > 1:
            query = query.where(ProcessInstance.status.in_(vals))
            
    if business_id:
        if "*" in business_id or "%" in business_id:
            query = query.where(ProcessInstance.business_id.like(business_id.replace("*", "%")))
        else:
            query = query.where(ProcessInstance.business_id == business_id)
            
    return db.scalars(query.order_by(ProcessInstance.created_at.desc()).offset(skip).limit(limit)).all()
