from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.middleware.auth import require_permission
from app.models.entities import MetricsSnapshot, User
from app.schemas.metrics import CustomReportRequest

router = APIRouter()


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), actor: User = Depends(require_permission("metrics", "read"))) -> dict:
    latest = db.scalar(select(MetricsSnapshot).where(MetricsSnapshot.org_id == actor.org_id).order_by(MetricsSnapshot.snapshot_date.desc()))
    if latest:
        return latest.payload
    return {"snapshot_date": datetime.utcnow().isoformat(), "activity_index": 0, "message_reach": 0, "attendance_anomaly_rate": 0, "work_order_sla": 1.0}


@router.get("/reports/summary")
def get_summary_report(
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("metrics", "read")),
) -> dict:
    rows = db.scalars(
        select(MetricsSnapshot)
        .where(MetricsSnapshot.org_id == actor.org_id)
        .order_by(MetricsSnapshot.snapshot_date.desc())
        .limit(30)
    ).all()
    
    if not rows:
        return {"report_date": datetime.utcnow().isoformat(), "status": "no_data"}
        
    return {
        "report_date": datetime.utcnow().isoformat(),
        "period_days": len(rows),
        "latest_snapshot": rows[0].payload,
        "history": [r.payload for r in rows]
    }
@router.get("/reports/advanced")
def get_advanced_report(
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("metrics", "read")),
) -> dict:
    from app.models.entities import ProcessInstance, Appointment, Expense, AuditLog, ProcessStatus
    from sqlalchemy import func
    
    # 1. Activity: Count of audit log events in last 24h
    day_ago = datetime.utcnow() - timedelta(days=1)
    activity_count = db.scalar(select(func.count(AuditLog.id)).where(AuditLog.org_id == actor.org_id, AuditLog.created_at >= day_ago)) or 0
    
    # 2. SLA Compliance: % of processes completed within SLA
    total_procs = db.scalar(select(func.count(ProcessInstance.id)).where(ProcessInstance.org_id == actor.org_id)) or 0
    overdue_count = db.scalar(select(func.count(ProcessInstance.id)).where(
        ProcessInstance.org_id == actor.org_id, 
        ProcessInstance.status == ProcessStatus.RUNNING,
        ProcessInstance.sla_due_at < datetime.utcnow()
    )) or 0
    sla_compliance = (total_procs - overdue_count) / total_procs if total_procs > 0 else 1.0
    
    # 3. Attendance/Occupancy anomalies: (Simulated or based on appointment stats)
    # Let's say count of cancelled appointments
    anomaly_count = db.scalar(select(func.count(Appointment.id)).where(Appointment.org_id == actor.org_id, Appointment.status == "cancelled")) or 0
    
    # 4. Expense summary
    expense_total = db.scalar(select(func.sum(Expense.amount)).where(Expense.org_id == actor.org_id)) or 0.0
    
    # 5. Message Reach
    total_org_users = db.scalar(select(func.count(User.id)).where(User.org_id == actor.org_id, User.is_active == True)) or 1
    touched_users = db.scalar(select(func.count(func.distinct(AuditLog.actor_id))).where(AuditLog.org_id == actor.org_id, AuditLog.created_at >= day_ago)) or 0
    message_reach = touched_users / total_org_users if total_org_users > 0 else 0.0

    return {
        "report_date": datetime.utcnow().isoformat(),
        "activity_24h": activity_count,
        "work_order_sla": round(sla_compliance, 2),
        "anomalies_count": anomaly_count,
        "message_reach": round(message_reach, 2),
        "expense_total": float(expense_total),
        "status": "active"
    }


@router.post("/reports/custom")
def get_custom_report(
    payload: CustomReportRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("metrics", "read")),
) -> dict:
    from sqlalchemy import and_
    query = select(MetricsSnapshot).where(MetricsSnapshot.org_id == actor.org_id)
    
    if payload.start_date:
        query = query.where(MetricsSnapshot.snapshot_date >= payload.start_date)
    if payload.end_date:
        query = query.where(MetricsSnapshot.snapshot_date <= payload.end_date)
        
    rows = db.scalars(query.order_by(MetricsSnapshot.snapshot_date.desc())).all()
    
    # Simple aggregation logic as a demonstration of "custom depth"
    summary = {
        "start_date": payload.start_date.isoformat() if payload.start_date else None,
        "end_date": payload.end_date.isoformat() if payload.end_date else None,
        "snapshots_found": len(rows),
        "metrics": {}
    }
    
    if "expenses" in payload.metric_types:
        summary["metrics"]["total_expenses"] = sum(float(r.payload.get("expense_total", 0)) for r in rows if "expense_total" in r.payload)
    
    if "sla" in payload.metric_types:
        avg_sla = sum(float(r.payload.get("work_order_sla", 0)) for r in rows if "work_order_sla" in r.payload) / len(rows) if rows else 1.0
        summary["metrics"]["avg_work_order_sla"] = round(avg_sla, 4)

    return {
        "custom_report": summary,
        "raw_data": [r.payload for r in rows] if len(rows) < 100 else "too many records to include raw data"
    }
