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
- Alembic setup with initial revision scaffold
- Docker compose for offline deployment

## Run locally
1. Copy `.env.example` to `.env`
2. Install dependencies: `pip install -r requirements.txt`
3. Initialize schema and seed RBAC: `python -m app.db.init_db`
4. Run API: `uvicorn app.main:app --reload`

## Run workers
- Worker: `celery -A app.tasks.celery_app:celery_app worker -l info`
- Beat: `celery -A app.tasks.celery_app:celery_app beat -l info`

## Export API
- Create export job: `POST /api/export/jobs` with body:
  - `fields`: list of allowed columns (`username`, `full_name`, `org_id`, `created_at`, `email`)
  - `desensitize`: boolean (forced true for non-admin exports)
  - `format`: `csv` or `xlsx`
- Non-admin users cannot export raw `email`; it is removed by policy.

## Workflow definition hints
- `first_node`: starting node key
- `assignees`: map of node key to user IDs or `role:<role_name>` (single or list)
- `variables`: start-instance payload variables usable in conditions
- `transitions`: per-node routing rules, e.g. `{"nodeA":{"approve":"nodeB"}}` or branch list
- `nodes`: per-node execution controls, e.g. `{"review":{"join_strategy":"quorum","quorum":2}}`
- condition examples:
  - `decision=='approve'`
  - `var:risk_level=='high'`

## Migrations
- Create revision: `alembic revision --autogenerate -m "message"`
- Apply migrations: `alembic upgrade head`

## Backup & recovery
- Backup DB: `python scripts/backup_db.py`
- Restore DB: `python scripts/restore_db.py --file backups/medical_ops_YYYYMMDD_HHMMSS.sql`

## HTTPS reverse proxy
- NGINX config is provided at `deploy/nginx.conf`
- Place TLS cert/key in `deploy/certs/server.crt` and `deploy/certs/server.key`
