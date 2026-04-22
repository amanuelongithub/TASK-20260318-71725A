from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from typing import List

from app.db.session import get_db
from app.middleware.auth import require_permission
from app.models.entities import User, Patient, Doctor, Appointment, Expense, ResourceApplication, CreditChange
from app.schemas.hospital import (
    PatientCreate, PatientUpdate, PatientOut,
    DoctorCreate, DoctorUpdate, DoctorOut,
    AppointmentCreate, AppointmentUpdate, AppointmentOut,
    ExpenseCreate, ExpenseUpdate, ExpenseOut,
    ResourceApplicationCreate, ResourceApplicationUpdate, ResourceApplicationOut,
    CreditChangeCreate, CreditChangeUpdate, CreditChangeOut
)

router = APIRouter()

# --- PATIENTS ---

@router.post("/patients", response_model=PatientOut)
def create_patient(
    payload: PatientCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("hospital", "create"))
):
    # Cross-org validation for user_id linkage
    if payload.user_id:
        target_user = db.scalar(select(User).where(User.id == payload.user_id, User.org_id == actor.org_id))
        if not target_user:
            raise HTTPException(status_code=400, detail="Linked user must belong to the same organization")

    # Using model properties for encryption is automatic via setters in Patient model
    item = Patient(
        org_id=actor.org_id,
        patient_number=payload.patient_number,
        full_name=payload.full_name,
        dob=payload.dob,
        user_id=payload.user_id
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item

@router.patch("/patients/{patient_id}", response_model=PatientOut)
def update_patient(
    patient_id: int,
    payload: PatientUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("hospital", "update"))
):
    item = db.scalar(select(Patient).where(Patient.id == patient_id, Patient.org_id == actor.org_id))
    if not item:
        raise HTTPException(status_code=404, detail="Patient not found")
    
    if payload.full_name is not None: item.full_name = payload.full_name
    if payload.dob is not None: item.dob = payload.dob
    if payload.user_id is not None:
        target_user = db.scalar(select(User).where(User.id == payload.user_id, User.org_id == actor.org_id))
        if not target_user:
            raise HTTPException(status_code=400, detail="Linked user must belong to the same organization")
        item.user_id = payload.user_id

    db.commit()
    db.refresh(item)
    return item

@router.get("/patients", response_model=List[PatientOut])
def list_patients(
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("hospital", "read"))
):
    return db.scalars(select(Patient).where(Patient.org_id == actor.org_id)).all()


# --- DOCTORS ---

@router.post("/doctors", response_model=DoctorOut)
def create_doctor(
    payload: DoctorCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("hospital", "create"))
):
    if payload.user_id:
        target_user = db.scalar(select(User).where(User.id == payload.user_id, User.org_id == actor.org_id))
        if not target_user:
            raise HTTPException(status_code=400, detail="Linked user must belong to the same organization")

    item = Doctor(
        org_id=actor.org_id,
        license_number=payload.license_number,
        full_name=payload.full_name,
        specialty=payload.specialty,
        is_active=payload.is_active,
        user_id=payload.user_id
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item

@router.patch("/doctors/{doctor_id}", response_model=DoctorOut)
def update_doctor(
    doctor_id: int,
    payload: DoctorUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("hospital", "update"))
):
    item = db.scalar(select(Doctor).where(Doctor.id == doctor_id, Doctor.org_id == actor.org_id))
    if not item:
        raise HTTPException(status_code=404, detail="Doctor not found")
    
    if payload.full_name is not None: item.full_name = payload.full_name
    if payload.specialty is not None: item.specialty = payload.specialty
    if payload.is_active is not None: item.is_active = payload.is_active
    if payload.user_id is not None:
        target_user = db.scalar(select(User).where(User.id == payload.user_id, User.org_id == actor.org_id))
        if not target_user:
            raise HTTPException(status_code=400, detail="Linked user must belong to the same organization")
        item.user_id = payload.user_id

    db.commit()
    db.refresh(item)
    return item

@router.get("/doctors", response_model=List[DoctorOut])
def list_doctors(
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("hospital", "read"))
):
    return db.scalars(select(Doctor).where(Doctor.org_id == actor.org_id)).all()


# --- APPOINTMENTS ---

@router.post("/appointments", response_model=AppointmentOut)
def create_appointment(
    payload: AppointmentCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("hospital", "create"))
):
    # CROSS-ENTITY ORG CHECK: patient_id and doctor_id must belong to the same org
    patient = db.scalar(select(Patient).where(Patient.id == payload.patient_id, Patient.org_id == actor.org_id))
    doctor = db.scalar(select(Doctor).where(Doctor.id == payload.doctor_id, Doctor.org_id == actor.org_id))
    if not patient or not doctor:
        raise HTTPException(status_code=400, detail="Patient and Doctor must belong to your organization")

    item = Appointment(
        org_id=actor.org_id,
        appointment_number=payload.appointment_number,
        patient_id=payload.patient_id,
        doctor_id=payload.doctor_id,
        status=payload.status,
        scheduled_time=payload.scheduled_time,
        notes=payload.notes
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item

@router.patch("/appointments/{appointment_id}", response_model=AppointmentOut)
def update_appointment(
    appointment_id: int,
    payload: AppointmentUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("hospital", "update"))
):
    item = db.scalar(select(Appointment).where(Appointment.id == appointment_id, Appointment.org_id == actor.org_id))
    if not item:
        raise HTTPException(status_code=404, detail="Appointment not found")

    if payload.patient_id:
        p = db.scalar(select(Patient).where(Patient.id == payload.patient_id, Patient.org_id == actor.org_id))
        if not p: raise HTTPException(status_code=400, detail="Invalid patient_id")
        item.patient_id = payload.patient_id
        
    if payload.doctor_id:
        d = db.scalar(select(Doctor).where(Doctor.id == payload.doctor_id, Doctor.org_id == actor.org_id))
        if not d: raise HTTPException(status_code=400, detail="Invalid doctor_id")
        item.doctor_id = payload.doctor_id

    if payload.status is not None: item.status = payload.status
    if payload.scheduled_time is not None: item.scheduled_time = payload.scheduled_time
    if payload.notes is not None: item.notes = payload.notes

    db.commit()
    db.refresh(item)
    return item

@router.get("/appointments", response_model=List[AppointmentOut])
def list_appointments(
    status: str | None = Query(None),
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("hospital", "read"))
):
    stmt = select(Appointment).where(Appointment.org_id == actor.org_id)
    if status:
        stmt = stmt.where(Appointment.status == status)
    return db.scalars(stmt).all()


# --- EXPENSES ---

@router.post("/expenses", response_model=ExpenseOut)
def create_expense(
    payload: ExpenseCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("hospital", "create"))
):
    item = Expense(
        org_id=actor.org_id,
        expense_number=payload.expense_number,
        amount=payload.amount,
        category=payload.category,
        status=payload.status,
        notes=payload.notes,
        submitted_by=actor.id
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item

@router.patch("/expenses/{expense_id}", response_model=ExpenseOut)
def update_expense(
    expense_id: int,
    payload: ExpenseUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("hospital", "update"))
):
    item = db.scalar(select(Expense).where(Expense.id == expense_id, Expense.org_id == actor.org_id))
    if not item:
        raise HTTPException(status_code=404, detail="Expense not found")

    if payload.amount is not None: item.amount = payload.amount
    if payload.category is not None: item.category = payload.category
    if payload.status is not None: item.status = payload.status
    if payload.notes is not None: item.notes = payload.notes

    db.commit()
    db.refresh(item)
    return item

@router.get("/expenses", response_model=List[ExpenseOut])
def list_expenses(
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("hospital", "read"))
):
    return db.scalars(select(Expense).where(Expense.org_id == actor.org_id)).all()


# --- RESOURCE APPLICATIONS ---

@router.post("/resource-applications", response_model=ResourceApplicationOut)
def create_resource_application(
    payload: ResourceApplicationCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("hospital", "create"))
):
    item = ResourceApplication(
        org_id=actor.org_id,
        application_number=payload.application_number,
        resource_name=payload.resource_name,
        quantity=payload.quantity,
        status=payload.status,
        applicant_id=actor.id
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item

@router.patch("/resource-applications/{application_id}", response_model=ResourceApplicationOut)
def update_resource_application(
    application_id: int,
    payload: ResourceApplicationUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("hospital", "update"))
):
    item = db.scalar(select(ResourceApplication).where(ResourceApplication.id == application_id, ResourceApplication.org_id == actor.org_id))
    if not item:
        raise HTTPException(status_code=404, detail="Resource Application not found")

    if payload.resource_name is not None: item.resource_name = payload.resource_name
    if payload.quantity is not None: item.quantity = payload.quantity
    if payload.status is not None: item.status = payload.status

    db.commit()
    db.refresh(item)
    return item

@router.get("/resource-applications", response_model=List[ResourceApplicationOut])
def list_resource_applications(
    status: str | None = Query(None),
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("hospital", "read"))
):
    stmt = select(ResourceApplication).where(ResourceApplication.org_id == actor.org_id)
    if status:
        stmt = stmt.where(ResourceApplication.status == status)
    return db.scalars(stmt).all()


# --- CREDIT CHANGES ---

@router.post("/credit-changes", response_model=CreditChangeOut)
def create_credit_change(
    payload: CreditChangeCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("hospital", "create"))
):
    # CROSS-ENTITY ORG CHECK: target_user_id must be org-scoped
    target_user = db.scalar(select(User).where(User.id == payload.target_user_id, User.org_id == actor.org_id))
    if not target_user:
         raise HTTPException(status_code=400, detail="Target user must belong to your organization")

    item = CreditChange(
        org_id=actor.org_id,
        change_number=payload.change_number,
        target_user_id=payload.target_user_id,
        amount=payload.amount,
        reason=payload.reason,
        status=payload.status
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item

@router.patch("/credit-changes/{change_id}", response_model=CreditChangeOut)
def update_credit_change(
    change_id: int,
    payload: CreditChangeUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("hospital", "update"))
):
    item = db.scalar(select(CreditChange).where(CreditChange.id == change_id, CreditChange.org_id == actor.org_id))
    if not item:
        raise HTTPException(status_code=404, detail="Credit Change not found")

    if payload.target_user_id:
        u = db.scalar(select(User).where(User.id == payload.target_user_id, User.org_id == actor.org_id))
        if not u: raise HTTPException(status_code=400, detail="Invalid target_user_id")
        item.target_user_id = payload.target_user_id

    if payload.amount is not None: item.amount = payload.amount
    if payload.reason is not None: item.reason = payload.reason
    if payload.status is not None: item.status = payload.status

    db.commit()
    db.refresh(item)
    return item

@router.get("/credit-changes", response_model=List[CreditChangeOut])
def list_credit_changes(
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("hospital", "read"))
):
    return db.scalars(select(CreditChange).where(CreditChange.org_id == actor.org_id)).all()
