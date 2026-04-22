# Medical Operations and Process Governance Middle Platform API

Expanded implementation baseline for your full plan.

## Implemented
- FastAPI layered architecture with domain/service/api separation
- SQLAlchemy models for identity, RBAC, workflow, exports, metrics, audit, data governance, attachments
- JWT auth, password hashing, lockout policy, org-level isolation
- Field encryption utility and SHA256 fingerprint deduplication
- Permission middleware driven by role-permission mappings
- Workflow APIs: create definition, start instance with idempotency keys, complete task
- Transition evaluator supports conditional branches and multi-node next steps
- Data governance APIs: versioning, validation, rollback lookup
- Export/audit/metrics APIs with permission checks
- CSV export generation with optional field desensitization
- Celery workers for daily metrics and SLA monitoring
- Alembic setup with multi-phase remediation migrations
- Docker compose for hardened production-ready deployment

## Security & Audit Compliance (Pass Criteria)

| Audit Goal | Implementation Detail | Verification Path |
|:---|:---|:---|
| **Hospital API Validity** | `Patient`/`Doctor` models use `@property` to align encrypted fields with Pydantic schemas. | `app/models/entities.py:291,308` |
| **Metrics Logic Fix** | `ProcessInstance.completed_at` tracks duration; aggregate jobs use it for velocity metrics. | `app/tasks/jobs.py:92`, `app/models/entities.py:111` |
| **HTTPS Default Posture** | `ALLOW_PLAIN_HTTP=False` in `config.py` and `.env`; enforced by middleware. | `app/main.py:27`, `app/core/config.py:19` |
| **Full-Chain Workflow** | Expense/Appointment workflows have specialized writeback logic & business timestamps. | `app/services/process_service.py:11-46` |
| **Async Deployment** | Celery `worker` and `beat` services integrated into the container stack. | `docker-compose.yml:25,35` |
| **Tenant Isolation** | All business logic (workflow, hospital, files) is partitioned by `org_id`. | `tests/test_security_audit.py:6` |
| **RBAC Integrity** | Multi-role permission matrix enforced by `require_permission` middleware. | `tests/test_security_audit.py:46` |
| **Data Dictionary** | Persistent, governed metadata stored in `data_dictionary_entries` table. | `app/services/dictionary_service.py:6` |

## Run locally
1. Copy `.env.example` to `.env`
2. Install dependencies: `pip install -r requirements.txt`
3. Start backing services: `docker-compose up -d db redis`
4. Apply migrations: `PYTHONPATH=. alembic upgrade head`
5. Seed initial data (RBAC, Dictionary): `python -m app.db.init_db`
6. Run API: `uvicorn app.main:app --reload`
7. (Optional) Start workers: `PYTHONPATH=. celery -A app.tasks.worker worker --loglevel=info`

## Metrics Semantics
- **Work Order SLA**: % of tasks completed before their `sla_due_at`.
- **Message Reach**: % of unique organization users who performed an action or were mentioned in an audit log in the last 24h.
- **Attendance Anomalies**: Ratio of overdue pending tasks per active user.
- **Activity Index**: Raw count of system events (AuditLog) in the last 24h.

## Verification Suite
Run the full validation suite to ensure audit compliance:
```bash
pytest
```
Individual critical tests:
- `tests/test_audit_remediation.py` (Idempotency, Identity, HTTPS)
- `tests/test_export_integration.py` (Export Lifecycle)
- `tests/test_security_audit.py` (Tenant Isolation, RBAC)

## Operational Reliability
- **Idempotency**: 24-hour window enforced at the service layer for `idempotency_key` and `business_id`.
- **Multi-Tenant Identity**: User identity is global; organizational context (org/role) is resolved via JWT-bound memberships without mutating the base record.
- **Performance**: Standardized indexing on all time-queried fields (`created_at`, `completed_at`, `sla_due_at`).
