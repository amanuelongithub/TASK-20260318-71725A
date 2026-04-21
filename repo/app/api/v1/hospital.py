from fastapi import APIRouter, Depends
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import Session
from datetime import datetime

from app.db.session import get_db
from app.middleware.auth import require_permission
from app.models.entities import User, Patient, Doctor, Appointment, Expense
from app.schemas.hospital import PatientOut, DoctorOut, AppointmentOut, ExpenseOut

router = APIRouter()


@router.get("/appointments", response_model=list[AppointmentOut])
def search_appointments(
    skip: int = 0,
    limit: int = 50,
    status: str | None = None,
    doctor_id: int | None = None,
    patient_id: int | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("hospital", "read")),
) -> list[AppointmentOut]:
    query = select(Appointment).where(Appointment.org_id == actor.org_id)
    if status:
        vals = [v.strip() for v in status.split(",") if v.strip()]
        if len(vals) == 1:
            query = query.where(Appointment.status == vals[0])
        else:
            query = query.where(Appointment.status.in_(vals))
    if doctor_id:
        query = query.where(Appointment.doctor_id == doctor_id)
    if patient_id:
        query = query.where(Appointment.patient_id == patient_id)
    if from_date:
        query = query.where(Appointment.scheduled_time >= from_date)
    if to_date:
        query = query.where(Appointment.scheduled_time <= to_date)
        
    rows = db.scalars(query.order_by(Appointment.scheduled_time.desc()).offset(skip).limit(limit)).all()
    from app.core.security import desensitize_response
    role_name = actor.role.name.value if actor.role else ""
    return desensitize_response(rows, role_name)


@router.get("/expenses", response_model=list[ExpenseOut])
def search_expenses(
    skip: int = 0,
    limit: int = 50,
    status: str | None = None,
    category: str | None = None,
    min_amount: float | None = None,
    max_amount: float | None = None,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("hospital", "read")),
) -> list[ExpenseOut]:
    query = select(Expense).where(Expense.org_id == actor.org_id)
    if status:
        vals = [v.strip() for v in status.split(",") if v.strip()]
        if len(vals) == 1:
            query = query.where(Expense.status == vals[0])
        else:
            query = query.where(Expense.status.in_(vals))
    if category:
        query = query.where(Expense.category == category)
    if min_amount is not None:
        query = query.where(Expense.amount >= min_amount)
    if max_amount is not None:
        query = query.where(Expense.amount <= max_amount)

    rows = db.scalars(query.order_by(Expense.created_at.desc()).offset(skip).limit(limit)).all()
    from app.core.security import desensitize_response
    role_name = actor.role.name.value if actor.role else ""
    return desensitize_response(rows, role_name)


@router.get("/patients", response_model=list[PatientOut])
def search_patients(
    skip: int = 0,
    limit: int = 50,
    name: str | None = None,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("hospital", "read")),
) -> list[PatientOut]:
    query = select(Patient).where(Patient.org_id == actor.org_id)
    if name:
        query = query.where(Patient.full_name.ilike(f"%{name}%"))
    
    rows = db.scalars(query.order_by(Patient.full_name.asc()).offset(skip).limit(limit)).all()
    from app.core.security import desensitize_response
    role_name = actor.role.name.value if actor.role else ""
    return desensitize_response(rows, role_name)


@router.get("/doctors", response_model=list[DoctorOut])
def search_doctors(
    skip: int = 0,
    limit: int = 50,
    specialty: str | None = None,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("hospital", "read")),
) -> list[DoctorOut]:
    query = select(Doctor).where(Doctor.org_id == actor.org_id)
    if specialty:
        query = query.where(Doctor.specialty.ilike(f"%{specialty}%"))
    
    rows = db.scalars(query.order_by(Doctor.full_name.asc()).offset(skip).limit(limit)).all()
    from app.core.security import desensitize_response
    role_name = actor.role.name.value if actor.role else ""
    return desensitize_response(rows, role_name)
