from datetime import datetime

from pydantic import BaseModel


class CreateProcessDefinitionRequest(BaseModel):
    name: str
    definition: dict


class StartProcessRequest(BaseModel):
    process_definition_id: int
    business_id: str
    idempotency_key: str
    variables: dict | None = None


class CompleteTaskRequest(BaseModel):
    decision: str
    comment: str | None = None


class ProcessInstanceOut(BaseModel):
    id: int
    status: str
    current_node: str
    sla_due_at: datetime | None


class TaskOut(BaseModel):
    id: int
    process_instance_id: int
    node_key: str
    status: str
    sla_due_at: datetime | None
