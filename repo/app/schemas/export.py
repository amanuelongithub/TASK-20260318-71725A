from pydantic import BaseModel


class ExportJobCreateRequest(BaseModel):
    entity_type: str  # users, patients, doctors, appointments, expenses, audit_logs
    fields: list[str]
    desensitize: bool = True
    format: str = "csv"
