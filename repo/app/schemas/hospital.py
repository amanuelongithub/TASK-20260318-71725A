from datetime import datetime
from pydantic import BaseModel


class PatientOut(BaseModel):
    id: int
    patient_number: str
    full_name: str
    dob: datetime | None
    created_at: datetime


class DoctorOut(BaseModel):
    id: int
    license_number: str
    full_name: str
    specialty: str | None
    is_active: bool
    created_at: datetime


class AppointmentOut(BaseModel):
    id: int
    appointment_number: str
    patient_id: int
    doctor_id: int
    status: str
    scheduled_time: datetime
    notes: str | None
    created_at: datetime


class ExpenseOut(BaseModel):
    id: int
    expense_number: str
    amount: float
    category: str
    status: str
    submitted_by: int
    notes: str | None
    created_at: datetime
