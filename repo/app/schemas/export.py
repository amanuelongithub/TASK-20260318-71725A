from pydantic import BaseModel


class ExportJobCreateRequest(BaseModel):
    fields: list[str]
    desensitize: bool = True
    format: str = "csv"
