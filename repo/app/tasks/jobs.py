from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import and_, case, func, select

from app.core.config import settings
from app.core.logging import logger
from app.db.session import SessionLocal
from app.models.entities import AuditLog, DataValidationIssue, ExportJob, MetricsSnapshot, ProcessDefinition, ProcessInstance, ProcessStatus, Role, RoleType, Task, TaskStatus, User
from app.services.export_service import generate_user_export_csv, generate_user_export_xlsx
from app.tasks.celery_app import celery_app


@celery_app.task(
    name="jobs.aggregate_all_daily_metrics",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3
)
def aggregate_all_daily_metrics() -> int:
    from app.models.entities import Organization
    db = SessionLocal()
    count = 0
    try:
        orgs = db.scalars(select(Organization)).all()
        for org in orgs:
            aggregate_daily_metrics.delay(org.id)
            count += 1
        return count
    finally:
        db.close()


@celery_app.task(
    name="jobs.backup_database",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3
)
def backup_database() -> str:
    import subprocess
    import os
    from app.core.config import settings
    # We can invoke the existing backup_db script
    try:
        if os.path.exists("scripts/backup_db.py"):
            subprocess.run(["python", "scripts/backup_db.py"], check=True)
            return "Backup executed successfully"
        return "Backup script not found"
    except Exception as e:
        return f"Backup failed: {e}"


@celery_app.task(
    name="jobs.aggregate_daily_metrics",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3
)
def aggregate_daily_metrics(org_id: int) -> int:
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        yesterday = now - timedelta(days=1)
        
        # 1. SLA Performance (% tasks on time)
        total_tasks = db.scalar(select(func.count(Task.id)).where(Task.org_id == org_id, Task.completed_at >= yesterday)) or 0
        on_time_tasks = db.scalar(select(func.count(Task.id)).where(
            Task.org_id == org_id, Task.completed_at >= yesterday, Task.completed_at <= Task.sla_due_at
        )) or 0
        sla_performance = float(on_time_tasks) / total_tasks if total_tasks > 0 else 1.0

        # 2. Workflow Velocity (Avg hours to complete instance)
        avg_velocity = db.scalar(select(func.avg(
            func.extract('epoch', ProcessInstance.sla_due_at - ProcessInstance.created_at) / 3600
        )).where(ProcessInstance.org_id == org_id, ProcessInstance.status == ProcessStatus.COMPLETED)) or 0.0

        # 3. Data Integrity (High severity issues)
        high_severity_issues = db.scalar(select(func.count(DataValidationIssue.id)).where(
            DataValidationIssue.org_id == org_id, DataValidationIssue.severity == "high", DataValidationIssue.created_at >= yesterday
        )) or 0

        # 4. System Usage (Participating users)
        active_users = db.scalar(select(func.count(func.distinct(Task.assignee_id))).where(
            Task.org_id == org_id, Task.created_at >= yesterday
        )) or 0

        payload = {
            "snapshot_date": now.isoformat(),
            "sla_performance": sla_performance,
            "avg_velocity_hours": float(avg_velocity),
            "high_severity_issues": int(high_severity_issues),
            "active_users": int(active_users),
            "total_completed_tasks_24h": int(total_tasks)
        }
        row = MetricsSnapshot(org_id=org_id, snapshot_date=now, payload=payload)
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


@celery_app.task(
    name="jobs.monitor_sla",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3
)
def monitor_sla() -> int:
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        overdue = db.scalars(
            select(ProcessInstance).where(ProcessInstance.status == ProcessStatus.RUNNING, ProcessInstance.sla_due_at < now)
        ).all()
        for item in overdue:
            db.add(
                AuditLog(
                    org_id=item.org_id,
                    actor_id=None,
                    event="process.sla_overdue",
                    event_metadata={"instance_id": item.id, "due_at": item.sla_due_at.isoformat() if item.sla_due_at else None},
                )
            )
        db.commit()
        return len(overdue)
    finally:
        db.close()


@celery_app.task(
    name="jobs.process_export_job",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)
def process_export_job(self, job_id: int) -> int:
    db = SessionLocal()
    try:
        job = db.scalar(select(ExportJob).where(ExportJob.id == job_id))
        if job is None:
            return 0
        job.status = "processing"
        db.commit()

        output_dir = Path(settings.file_storage_path) / "exports"
        output_dir.mkdir(parents=True, exist_ok=True)
        export_format = str(job.fields.get("format", "csv")).lower()
        extension = "xlsx" if export_format == "xlsx" else "csv"
        output_path = output_dir / f"export_job_{job.id}.{extension}"
        columns = job.fields.get("columns", [])
        desensitize = bool(job.fields.get("desensitize", True))
        if export_format == "xlsx":
            generate_user_export_xlsx(db, job.org_id, columns, output_path, desensitize)
        else:
            generate_user_export_csv(db, job.org_id, columns, output_path, desensitize)

        job.output_path = str(output_path)
        job.status = "completed"
        db.add(
            AuditLog(
                org_id=job.org_id,
                actor_id=job.requested_by,
                event="export.job_completed",
                event_metadata={"job_id": job.id, "output_path": job.output_path},
            )
        )
        db.commit()
        return job.id
    except Exception as exc:  # noqa: BLE001
        job = db.scalar(select(ExportJob).where(ExportJob.id == job_id))
        if job:
            job.status = "failed"
            db.add(
                AuditLog(
                    org_id=job.org_id,
                    actor_id=job.requested_by,
                    event="export.job_failed",
                    event_metadata={"job_id": job.id, "error": str(exc)},
                )
            )
            db.commit()
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(
    name="jobs.send_task_reminders",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3
)
def send_task_reminders() -> int:
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        soon = now + timedelta(hours=6)
        rows = db.scalars(
            select(Task).where(Task.status == TaskStatus.PENDING, Task.sla_due_at.is_not(None), Task.sla_due_at <= soon)
        ).all()
        for task in rows:
            db.add(
                AuditLog(
                    org_id=task.org_id,
                    actor_id=task.assignee_id,
                    event="task.reminder",
                    event_metadata={"task_id": task.id, "due_at": task.sla_due_at.isoformat() if task.sla_due_at else None},
                )
            )
        db.commit()
        return len(rows)
    finally:
        db.close()


@celery_app.task(
    name="jobs.escalate_overdue_tasks",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3
)
def escalate_overdue_tasks() -> int:
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        rows = db.scalars(
            select(Task).where(Task.status == TaskStatus.PENDING, Task.sla_due_at.is_not(None), Task.sla_due_at < now)
        ).all()
        for task in rows:
            admin_role = db.scalar(select(Role).where(Role.name == RoleType.ADMIN))
            admin_user = (
                db.scalar(select(User).where(User.org_id == task.org_id, User.role_id == admin_role.id, User.is_active.is_(True)))
                if admin_role
                else None
            )
            if admin_user:
                task.assignee_id = admin_user.id
            db.add(
                AuditLog(
                    org_id=task.org_id,
                    actor_id=None,
                    event="task.escalated",
                    event_metadata={"task_id": task.id, "assignee_id": task.assignee_id, "reassigned_to_admin": bool(admin_user)},
                )
            )
        db.commit()
        return len(rows)
    finally:
        db.close()


@celery_app.task(
    name="jobs.prune_old_backups",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3
)
def prune_old_backups() -> int:
    backup_dir = Path("backups")
    if not backup_dir.exists():
        return 0
    
    count = 0
    now = datetime.utcnow()
    retention_limit = now - timedelta(days=30)
    
    for f in backup_dir.glob("medical_ops_*.sql"):
        try:
            ts_str = f.stem.replace("medical_ops_", "")
            file_ts = datetime.strptime(ts_str, "%Y%m%d_%H%M%S")
            if file_ts < retention_limit:
                f.unlink()
                count += 1
        except (ValueError, OSError):
            mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=None)
            if mtime < retention_limit:
                f.unlink()
                count += 1
                
    return count


@celery_app.task(
    name="jobs.handle_task_timeouts",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3
)
def handle_task_timeouts() -> int:
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        expired_tasks = db.scalars(
            select(Task).where(Task.status == TaskStatus.PENDING, Task.sla_due_at < now)
        ).all()
        
        count = 0
        for task in expired_tasks:
            # Check node config for auto-action
            instance = db.scalar(select(ProcessInstance).where(ProcessInstance.id == task.process_instance_id))
            if not instance: continue
            
            definition = db.scalar(select(ProcessDefinition).where(ProcessDefinition.id == instance.process_definition_id))
            if not definition: continue
            
            node_cfg = definition.definition.get("nodes", {}).get(task.node_key, {})
            on_timeout = str(node_cfg.get("on_timeout", "escalate")).lower()
            
            if on_timeout in {"approve", "reject"}:
                actor = db.scalar(select(User).where(User.id == task.assignee_id))
                if actor:
                    from app.services.process_service import complete_task
                    try:
                        complete_task(db, actor, task.id, on_timeout, f"Auto-{on_timeout}d due to timeout")
                    except Exception as e:
                        # Log error if transition fails but don't crash job
                        logger.error(f"Error auto-transitioning task {task.id}: {e}")

            else:
                # Default to escalation
                admin_role = db.scalar(select(Role).where(Role.name == RoleType.ADMIN))
                admin_user = db.scalar(select(User).where(User.org_id == task.org_id, User.role_id == admin_role.id, User.is_active.is_(True))) if admin_role else None
                if admin_user and task.assignee_id != admin_user.id:
                    task.assignee_id = admin_user.id
                    db.add(AuditLog(
                        org_id=task.org_id, actor_id=None, event="task.escalated",
                        event_metadata={"task_id": task.id, "reason": "timeout", "new_assignee": admin_user.id}
                    ))
            count += 1
            
        db.commit()
        return count
    finally:
        db.close()


@celery_app.task(
    name="jobs.prune_old_exports",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3
)
def prune_old_exports() -> int:
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        limit = now - timedelta(days=7)
        old_jobs = db.scalars(
            select(ExportJob).where(ExportJob.status == "completed", ExportJob.created_at < limit)
        ).all()
        
        count = 0
        for job in old_jobs:
            if job.output_path:
                p = Path(job.output_path)
                if p.exists():
                    try:
                        p.unlink()
                    except OSError:
                        pass
                job.status = "expired"
                count += 1
        
        db.commit()
        return count
    finally:
        db.close()


@celery_app.task(
    name="jobs.sign_audit_log_batches",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3
)
def sign_audit_log_batches() -> int:
    import hashlib
    import hmac
    
    db = SessionLocal()
    try:
        from app.models.entities import AuditLogBatchSignature
        last_signed_id = db.scalar(select(func.max(AuditLogBatchSignature.last_log_id))) or 0
        
        logs = db.scalars(
            select(AuditLog).where(AuditLog.id > last_signed_id).order_by(AuditLog.id.asc()).limit(100)
        ).all()
        
        if not logs:
            return 0
            
        batch_content = "".join([f"{l.id}{l.event}{l.created_at.isoformat()}" for l in logs])
        batch_hash = hashlib.sha256(batch_content.encode()).hexdigest()
        signature = hmac.new(settings.secret_key.encode(), batch_hash.encode(), hashlib.sha256).hexdigest()
        
        db.add(AuditLogBatchSignature(
            org_id=logs[-1].org_id,
            last_log_id=logs[-1].id,
            batch_hash=batch_hash,
            signature=signature
        ))
        db.commit()
        return len(logs)
    finally:
        db.close()
