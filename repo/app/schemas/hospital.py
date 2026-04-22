from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class PatientCreate(BaseModel):
    patient_number: str = Field(min_length=1, max_length=64)
    full_name: str = Field(min_length=1, max_length=255)
    dob: datetime | None = None
    phone_number: str | None = Field(default=None, max_length=64)
    user_id: int | None = None


class PatientUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    dob: datetime | None = None
    phone_number: str | None = Field(default=None, max_length=64)
    user_id: int | None = None


class DoctorCreate(BaseModel):
    license_number: str = Field(min_length=1, max_length=64)
    full_name: str = Field(min_length=1, max_length=255)
    specialty: str | None = Field(default=None, max_length=120)
    is_active: bool = True
    user_id: int | None = None


class DoctorUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    specialty: str | None = Field(default=None, max_length=120)
    is_active: bool | None = None
    user_id: int | None = None


class AppointmentCreate(BaseModel):
    appointment_number: str = Field(min_length=1, max_length=64)
    patient_id: int
    doctor_id: int
    status: str = Field(default="scheduled", min_length=1, max_length=32)
    scheduled_time: datetime
    notes: str | None = None


class AppointmentUpdate(BaseModel):
    patient_id: int | None = None
    doctor_id: int | None = None
    status: str | None = Field(default=None, min_length=1, max_length=32)
    scheduled_time: datetime | None = None
    notes: str | None = None


class ExpenseCreate(BaseModel):
    expense_number: str = Field(min_length=1, max_length=64)
    amount: float
    category: str = Field(min_length=1, max_length=64)
    status: str = Field(default="pending", min_length=1, max_length=32)
    notes: str | None = None


class ExpenseUpdate(BaseModel):
    amount: float | None = None
    category: str | None = Field(default=None, min_length=1, max_length=64)
    status: str | None = Field(default=None, min_length=1, max_length=32)
    notes: str | None = None


class ResourceApplicationCreate(BaseModel):
    application_number: str = Field(min_length=1, max_length=64)
    resource_name: str = Field(min_length=1, max_length=255)
    quantity: int = Field(ge=1)
    status: str = Field(default="pending", min_length=1, max_length=32)


class ResourceApplicationUpdate(BaseModel):
    resource_name: str | None = Field(default=None, min_length=1, max_length=255)
    quantity: int | None = Field(default=None, ge=1)
    status: str | None = Field(default=None, min_length=1, max_length=32)


class CreditChangeCreate(BaseModel):
    change_number: str = Field(min_length=1, max_length=64)
    target_user_id: int
    amount: float
    reason: str = Field(min_length=1)
    status: str = Field(default="pending", min_length=1, max_length=32)


class CreditChangeUpdate(BaseModel):
    target_user_id: int | None = None
    amount: float | None = None
    reason: str | None = Field(default=None, min_length=1)
    status: str | None = Field(default=None, min_length=1, max_length=32)


class PatientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    patient_number: str
    full_name: str
    dob: datetime | None
    created_at: datetime


class DoctorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    license_number: str
    full_name: str
    specialty: str | None
    is_active: bool
    created_at: datetime


class AppointmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    appointment_number: str
    patient_id: int
    doctor_id: int
    status: str
    scheduled_time: datetime
    notes: str | None
    created_at: datetime


class ExpenseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    expense_number: str
    amount: float
    category: str
    status: str
    submitted_by: int
    notes: str | None
    created_at: datetime


class ResourceApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    application_number: str
    resource_name: str
    quantity: int
    applicant_id: int
    status: str
    approved_at: datetime | None
    created_at: datetime


class CreditChangeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    change_number: str
    target_user_id: int
    amount: float
    reason: str
    status: str
    approved_at: datetime | None
    created_at: datetime
