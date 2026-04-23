from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime

from app.core.security import desensitize_response, deterministic_hash
from app.db.session import get_db
from app.middleware.auth import require_permission, AuthenticatedActor
from app.models.entities import User, Patient, Doctor, Appointment, Expense, ResourceApplication, CreditChange
from app.schemas.hospital import (
    PatientCreate, PatientUpdate, PatientOut,
    DoctorCreate, DoctorUpdate, DoctorOut,
    AppointmentCreate, AppointmentUpdate, AppointmentOut,
    ExpenseCreate, ExpenseUpdate, ExpenseOut,
    ResourceApplicationOut,
    ResourceApplicationCreate, ResourceApplicationUpdate,
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
        from app.models.entities import OrganizationMembership
        is_member = OrganizationMembership.is_user_active_in_org(db, payload.user_id, actor.org_id)
        if not is_member:
            raise HTTPException(status_code=400, detail="Linked user must belong to the same organization")

    # Using model properties for encryption is automatic via setters in Patient model
    item = Patient(
        org_id=actor.org_id,
        patient_number=payload.patient_number,
        full_name=payload.full_name,
        dob=payload.dob,
        phone_number=payload.phone_number,
        user_id=payload.user_id
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return desensitize_response(item, actor.role.name)

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
    
    # OBJECT-LEVEL AUTHORIZATION
    from app.models.entities import RoleType
    is_admin_or_reviewer = actor.role.name in {RoleType.ADMIN, RoleType.REVIEWER}
    is_owner = (item.user_id == actor.id)
    
    if not is_admin_or_reviewer and not is_owner:
        raise HTTPException(status_code=403, detail="Forbidden: You can only update your own patient record.")
    
    if payload.full_name is not None: item.full_name = payload.full_name
    if payload.dob is not None: item.dob = payload.dob
    if payload.phone_number is not None: item.phone_number = payload.phone_number
    if payload.user_id is not None:
        from app.models.entities import OrganizationMembership
        is_member = OrganizationMembership.is_user_active_in_org(db, payload.user_id, actor.org_id)
        if not is_member:
            raise HTTPException(status_code=400, detail="Linked user must belong to the same organization")
        item.user_id = payload.user_id

    db.commit()
    db.refresh(item)
    return desensitize_response(item, actor.role.name)

@router.get("/patients", response_model=List[PatientOut])
def list_patients(
    patient_number: str | None = Query(None),
    full_name: str | None = Query(None),
    dob_start: datetime | None = Query(None),
    dob_end: datetime | None = Query(None),
    user_id: int | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    sort_by: str = Query("created_at"),
    order: str = Query("desc", regex="^(asc|desc)$"),
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(require_permission("hospital", "read"))
):
    from sqlalchemy import asc, desc
    stmt = select(Patient).where(Patient.org_id == actor.org_id)
    
    if patient_number:
        stmt = stmt.where(Patient.patient_number_hash == deterministic_hash(patient_number))
    if full_name:
        stmt = stmt.where(Patient.full_name.ilike(f"%{full_name}%"))
    if dob_start:
        stmt = stmt.where(Patient.dob >= dob_start)
    if dob_end:
        stmt = stmt.where(Patient.dob <= dob_end)
    if user_id:
        stmt = stmt.where(Patient.user_id == user_id)
        
    # Sorting logic
    col = getattr(Patient, sort_by, Patient.created_at)
    stmt = stmt.order_by(asc(col) if order == "asc" else desc(col))
    
    # Pagination
    stmt = stmt.offset(offset).limit(limit)
    
    results = db.scalars(stmt).all()
    return desensitize_response(results, actor.role.name)


# --- DOCTORS ---

@router.post("/doctors", response_model=DoctorOut)
def create_doctor(
    payload: DoctorCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("hospital", "create"))
):
    if payload.user_id:
        from app.models.entities import OrganizationMembership
        is_member = OrganizationMembership.is_user_active_in_org(db, payload.user_id, actor.org_id)
        if not is_member:
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
    return desensitize_response(item, actor.role.name)

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
        
    # OBJECT-LEVEL AUTHORIZATION
    from app.models.entities import RoleType
    is_admin_or_reviewer = actor.role.name in {RoleType.ADMIN, RoleType.REVIEWER}
    is_owner = (item.user_id == actor.id)
    
    if not is_admin_or_reviewer and not is_owner:
        raise HTTPException(status_code=403, detail="Forbidden: You can only update your own doctor record.")
    
    if payload.full_name is not None: item.full_name = payload.full_name
    if payload.specialty is not None: item.specialty = payload.specialty
    if payload.is_active is not None: item.is_active = payload.is_active
    if payload.user_id is not None:
        from app.models.entities import OrganizationMembership
        is_member = OrganizationMembership.is_user_active_in_org(db, payload.user_id, actor.org_id)
        if not is_member:
            raise HTTPException(status_code=400, detail="Linked user must belong to the same organization")
        item.user_id = payload.user_id

    db.commit()
    db.refresh(item)
    return desensitize_response(item, actor.role.name)

@router.get("/doctors", response_model=List[DoctorOut])
def list_doctors(
    license_number: str | None = Query(None),
    full_name: str | None = Query(None),
    specialty: str | None = Query(None),
    is_active: bool | None = Query(None),
    user_id: int | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    sort_by: str = Query("created_at"),
    order: str = Query("desc", regex="^(asc|desc)$"),
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(require_permission("hospital", "read"))
):
    from sqlalchemy import asc, desc
    stmt = select(Doctor).where(Doctor.org_id == actor.org_id)
    
    if license_number:
        stmt = stmt.where(Doctor.license_number_hash == deterministic_hash(license_number))
    if full_name:
        stmt = stmt.where(Doctor.full_name.ilike(f"%{full_name}%"))
    if specialty:
        stmt = stmt.where(Doctor.specialty.ilike(f"%{specialty}%"))
    if is_active is not None:
        stmt = stmt.where(Doctor.is_active == is_active)
    if user_id:
        stmt = stmt.where(Doctor.user_id == user_id)
        
    col = getattr(Doctor, sort_by, Doctor.created_at)
    stmt = stmt.order_by(asc(col) if order == "asc" else desc(col))
    stmt = stmt.offset(offset).limit(limit)
    
    results = db.scalars(stmt).all()
    return desensitize_response(results, actor.role.name)


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
    return desensitize_response(item, actor.role.name)

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

    # OBJECT-LEVEL AUTHORIZATION
    from app.models.entities import RoleType, Patient, Doctor
    is_admin_or_reviewer = actor.role.name in {RoleType.ADMIN, RoleType.REVIEWER}
    
    # Check if actor is the patient or doctor in this appointment
    patient = db.scalar(select(Patient).where(Patient.id == item.patient_id))
    doctor = db.scalar(select(Doctor).where(Doctor.id == item.doctor_id))
    is_involved = (patient and patient.user_id == actor.id) or (doctor and doctor.user_id == actor.id)
    
    if not is_admin_or_reviewer and not is_involved:
        raise HTTPException(status_code=403, detail="Forbidden: You must be the doctor or patient of this appointment to update it.")

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
    return desensitize_response(item, actor.role.name)

@router.get("/appointments", response_model=List[AppointmentOut])
def list_appointments(
    appointment_number: str | None = Query(None),
    patient_id: int | None = Query(None),
    doctor_id: int | None = Query(None),
    status: str | None = Query(None),
    scheduled_start: datetime | None = Query(None),
    scheduled_end: datetime | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    sort_by: str = Query("scheduled_time"),
    order: str = Query("desc", regex="^(asc|desc)$"),
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(require_permission("hospital", "read"))
):
    from sqlalchemy import asc, desc
    stmt = select(Appointment).where(Appointment.org_id == actor.org_id)
    
    if appointment_number:
        stmt = stmt.where(Appointment.appointment_number == appointment_number)
    if patient_id:
        stmt = stmt.where(Appointment.patient_id == patient_id)
    if doctor_id:
        stmt = stmt.where(Appointment.doctor_id == doctor_id)
    if status:
        stmt = stmt.where(Appointment.status == status)
    if scheduled_start:
        stmt = stmt.where(Appointment.scheduled_time >= scheduled_start)
    if scheduled_end:
        stmt = stmt.where(Appointment.scheduled_time <= scheduled_end)
        
    col = getattr(Appointment, sort_by, Appointment.scheduled_time)
    stmt = stmt.order_by(asc(col) if order == "asc" else desc(col))
    stmt = stmt.offset(offset).limit(limit)
    
    results = db.scalars(stmt).all()
    return desensitize_response(results, actor.role.name)


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
    return desensitize_response(item, actor.role.name)

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

    # OBJECT-LEVEL AUTHORIZATION
    from app.models.entities import RoleType
    is_admin_or_reviewer = actor.role.name in {RoleType.ADMIN, RoleType.REVIEWER}
    is_owner = (item.submitted_by == actor.id)
    
    if not is_admin_or_reviewer and not is_owner:
        raise HTTPException(status_code=403, detail="Forbidden: You can only update your own expense reports.")

    if payload.amount is not None: item.amount = payload.amount
    if payload.category is not None: item.category = payload.category
    if payload.status is not None: item.status = payload.status
    if payload.notes is not None: item.notes = payload.notes

    db.commit()
    db.refresh(item)
    return desensitize_response(item, actor.role.name)

@router.get("/expenses", response_model=List[ExpenseOut])
def list_expenses(
    expense_number: str | None = Query(None),
    category: str | None = Query(None),
    status: str | None = Query(None),
    min_amount: float | None = Query(None),
    max_amount: float | None = Query(None),
    submitted_by: int | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    sort_by: str = Query("created_at"),
    order: str = Query("desc", regex="^(asc|desc)$"),
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(require_permission("hospital", "read"))
):
    from sqlalchemy import asc, desc
    stmt = select(Expense).where(Expense.org_id == actor.org_id)
    
    if expense_number:
        stmt = stmt.where(Expense.expense_number == expense_number)
    if category:
        stmt = stmt.where(Expense.category.ilike(f"%{category}%"))
    if status:
        stmt = stmt.where(Expense.status == status)
    if min_amount is not None:
        stmt = stmt.where(Expense.amount >= min_amount)
    if max_amount is not None:
        stmt = stmt.where(Expense.amount <= max_amount)
    if submitted_by:
        stmt = stmt.where(Expense.submitted_by == submitted_by)
        
    col = getattr(Expense, sort_by, Expense.created_at)
    stmt = stmt.order_by(asc(col) if order == "asc" else desc(col))
    stmt = stmt.offset(offset).limit(limit)
    
    results = db.scalars(stmt).all()
    return desensitize_response(results, actor.role.name)


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
    return desensitize_response(item, actor.role.name)

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

    # OBJECT-LEVEL AUTHORIZATION
    from app.models.entities import RoleType
    is_admin_or_reviewer = actor.role.name in {RoleType.ADMIN, RoleType.REVIEWER}
    is_owner = (item.applicant_id == actor.id)
    
    if not is_admin_or_reviewer and not is_owner:
        raise HTTPException(status_code=403, detail="Forbidden: You can only update your own resource applications.")

    if payload.resource_name is not None: item.resource_name = payload.resource_name
    if payload.quantity is not None: item.quantity = payload.quantity
    if payload.status is not None: item.status = payload.status

    db.commit()
    db.refresh(item)
    return desensitize_response(item, actor.role.name)

@router.get("/resource-applications", response_model=List[ResourceApplicationOut])
def list_resource_applications(
    application_number: str | None = Query(None),
    resource_name: str | None = Query(None),
    status: str | None = Query(None),
    applicant_id: int | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    sort_by: str = Query("created_at"),
    order: str = Query("desc", regex="^(asc|desc)$"),
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(require_permission("hospital", "read"))
):
    from sqlalchemy import asc, desc
    stmt = select(ResourceApplication).where(ResourceApplication.org_id == actor.org_id)
    if application_number:
        stmt = stmt.where(ResourceApplication.application_number == application_number)
    if resource_name:
        stmt = stmt.where(ResourceApplication.resource_name.ilike(f"%{resource_name}%"))
    if status:
        stmt = stmt.where(ResourceApplication.status == status)
    if applicant_id:
        stmt = stmt.where(ResourceApplication.applicant_id == applicant_id)
        
    col = getattr(ResourceApplication, sort_by, ResourceApplication.created_at)
    stmt = stmt.order_by(asc(col) if order == "asc" else desc(col))
    stmt = stmt.offset(offset).limit(limit)
    
    results = db.scalars(stmt).all()
    return desensitize_response(results, actor.role.name)


# --- CREDIT CHANGES ---

@router.post("/credit-changes", response_model=CreditChangeOut)
def create_credit_change(
    payload: CreditChangeCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("hospital", "create"))
):
    # CROSS-ENTITY ORG CHECK: target_user_id must be org-scoped
    from app.models.entities import OrganizationMembership
    is_member = OrganizationMembership.is_user_active_in_org(db, payload.target_user_id, actor.org_id)
    if not is_member:
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
    return desensitize_response(item, actor.role.name)

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

    # OBJECT-LEVEL AUTHORIZATION
    from app.models.entities import RoleType
    is_admin_or_reviewer = actor.role.name in {RoleType.ADMIN, RoleType.REVIEWER}
    is_owner = (item.target_user_id == actor.id)
    
    if not is_admin_or_reviewer and not is_owner:
        raise HTTPException(status_code=403, detail="Forbidden: You can only update your own credit change records.")

    if payload.target_user_id:
        from app.models.entities import OrganizationMembership
        is_member = OrganizationMembership.is_user_active_in_org(db, payload.target_user_id, actor.org_id)
        if not is_member: raise HTTPException(status_code=400, detail="Invalid target_user_id")
        item.target_user_id = payload.target_user_id

    if payload.amount is not None: item.amount = payload.amount
    if payload.reason is not None: item.reason = payload.reason
    if payload.status is not None: item.status = payload.status

    db.commit()
    db.refresh(item)
    return desensitize_response(item, actor.role.name)

@router.get("/credit-changes", response_model=List[CreditChangeOut])
def list_credit_changes(
    change_number: str | None = Query(None),
    target_user_id: int | None = Query(None),
    status: str | None = Query(None),
    min_amount: float | None = Query(None),
    max_amount: float | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    sort_by: str = Query("created_at"),
    order: str = Query("desc", regex="^(asc|desc)$"),
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(require_permission("hospital", "read"))
):
    from sqlalchemy import asc, desc
    stmt = select(CreditChange).where(CreditChange.org_id == actor.org_id)
    if change_number:
        stmt = stmt.where(CreditChange.change_number == change_number)
    if target_user_id:
        stmt = stmt.where(CreditChange.target_user_id == target_user_id)
    if status:
        stmt = stmt.where(CreditChange.status == status)
    if min_amount is not None:
        stmt = stmt.where(CreditChange.amount >= min_amount)
    if max_amount is not None:
        stmt = stmt.where(CreditChange.amount <= max_amount)
        
    col = getattr(CreditChange, sort_by, CreditChange.created_at)
    stmt = stmt.order_by(asc(col) if order == "asc" else desc(col))
    stmt = stmt.offset(offset).limit(limit)
    
    results = db.scalars(stmt).all()
    return desensitize_response(results, actor.role.name)
