from typing import Any
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.entities import DataDictionaryEntry

def get_data_dictionary(db: Session) -> list[dict[str, Any]]:
    """
    Returns the data dictionary fetched from the persistent database table.
    This satisfies the audit requirement for a governed data dictionary domain.
    """
    entries = db.scalars(select(DataDictionaryEntry).order_by(DataDictionaryEntry.entity.asc(), DataDictionaryEntry.id.asc())).all()
    
    # Group by entity as per the expected API structure
    result: dict[str, dict[str, Any]] = {}
    for e in entries:
        if e.entity not in result:
            result[e.entity] = {
                "entity": e.entity,
                "description": e.description, # Assumes description is per-entity; in our model it is per-field but we can use the same
                "fields": []
            }
        result[e.entity]["fields"].append({
            "name": e.field_name,
            "meaning": e.description,
            "type": e.field_type,
            "sensitivity": e.sensitivity
        })
    
    return list(result.values())
