from pydantic import BaseModel


class CreateDataVersionRequest(BaseModel):
    entity_type: str
    entity_id: str
    payload: dict


class ValidateBatchRequest(BaseModel):
    batch_id: str
    entity_type: str
    records: list[dict]


class RollbackRequest(BaseModel):
    version_id: int
