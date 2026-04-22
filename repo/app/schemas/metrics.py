from datetime import datetime
from pydantic import BaseModel, Field


class CustomReportRequest(BaseModel):
    start_date: datetime | None = None
    end_date: datetime | None = None
    metric_types: list[str] = Field(default_factory=lambda: ["sla", "activity", "expenses"])
    group_by: str | None = None # e.g., 'day', 'week'
