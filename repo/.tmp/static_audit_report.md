# Static Audit Report: Medical Operations and Process Governance Middle Platform API

## 1. Verdict
- Overall conclusion: **Fail**

## 2. Scope and Static Verification Boundary
- Reviewed: repository structure, README/config examples, FastAPI entry points, route registration, auth/RBAC middleware, core services, ORM models, Alembic migrations, task definitions, backup scripts, and test files.
- Not reviewed: runtime behavior, actual DB/Redis/Celery/NGINX processes, Docker behavior, HTTPS termination in deployment, worker scheduling outcomes, and external command execution results.
- Intentionally not executed: project startup, tests, Docker, migrations, workers, backup/restore commands, network calls.
- Manual verification required for: real PostgreSQL migration application order, actual HTTPS-only deployment, Celery scheduling reliability, backup/restore execution, and any runtime concurrency behavior.

## 3. Repository / Requirement Mapping Summary
- Prompt goal: deliver a FastAPI + PostgreSQL middle-platform API for identity/org isolation, four-tier RBAC, operations analysis/search/reporting, export with whitelist/desensitization/auditability, workflow approval with SLA/reminders/audit trail/idempotency, data governance/versioning/rollback/lineage/backups, and security/compliance controls.
- Main mapped areas: `app/api/v1/*.py` for interfaces, `app/services/*.py` for domain logic, `app/models/entities.py` and `alembic/versions/*.py` for persistence/constraints, `app/middleware/auth.py` for authz, `app/tasks/jobs.py` for scheduling/backup/reminders, `tests/*.py` for static coverage evidence.

## 4. Section-by-section Review

### 1. Hard Gates
#### 1.1 Documentation and static verifiability
- Conclusion: **Partial Pass**
- Rationale: README provides basic install/run/migration/backup steps, but no test command documentation and no guidance for required PostgreSQL/Redis/Celery prerequisites beyond dependency names; static verification is possible but incomplete. `README.md:20`, `README.md:26`, `README.md:47`, `README.md:51`
- Evidence: `README.md:20-57`, `.env.example:1-11`, `pyproject.toml:1-23`

#### 1.2 Material deviation from the Prompt
- Conclusion: **Fail**
- Rationale: the code targets the stated domain, but major prompt requirements are weakened or narrowed: unauthorized org joining is possible during registration, operations analysis/reporting is only partially implemented, exports are user-only, and data rollback is only implemented for two entity types. `app/services/auth_service.py:17-21`, `app/services/export_service.py:36-49`, `app/api/v1/metrics.py:22-78`, `app/services/data_governance_service.py:156-191`
- Evidence: `app/services/auth_service.py:16-61`, `app/api/v1/hospital.py:14-112`, `app/api/v1/metrics.py:22-78`, `app/services/export_service.py:36-70`, `app/services/data_governance_service.py:156-191`

### 2. Delivery Completeness
#### 2.1 Coverage of explicit core requirements
- Conclusion: **Fail**
- Rationale: implemented pieces exist for auth, workflows, exports, metrics, files, and governance, but several explicit prompt requirements are missing or only partial: secure organization join governance, customizable reporting, full advanced filtering breadth, generic workflow writeback, full rollback scope, and scheduler failure compensation capped at 3 retries across scheduled jobs. `app/services/auth_service.py:16-61`, `app/api/v1/metrics.py:22-78`, `app/api/v1/hospital.py:79-112`, `app/services/process_service.py:11-21`, `app/services/data_governance_service.py:156-191`, `app/tasks/jobs.py:14-359`
- Evidence: `app/api/v1/auth.py:13-56`, `app/api/v1/hospital.py:14-112`, `app/api/v1/metrics.py:14-78`, `app/services/process_service.py:115-184`, `app/services/data_governance_service.py:47-191`, `app/tasks/jobs.py:112-120`

#### 2.2 Basic end-to-end deliverable vs partial/demo
- Conclusion: **Partial Pass**
- Rationale: the repository is a real multi-module service, not a single-file demo, but important flows remain incomplete or rely on broad assumptions not exposed as productized APIs, especially org membership lifecycle and generalized governance/export/reporting. `app/api/router.py:1-12`, `app/services/auth_service.py:145-180`
- Evidence: `app/`, `alembic/`, `tests/`, `README.md:5-57`

### 3. Engineering and Architecture Quality
#### 3.1 Structure and module decomposition
- Conclusion: **Pass**
- Rationale: layout is reasonable for the scope, with separation across API, services, models, DB, middleware, tasks, and schemas. `app/api/router.py:1-12`, `README.md:5-18`
- Evidence: `app/api/router.py:1-12`, `app/services/*.py`, `app/models/entities.py:17-325`

#### 3.2 Maintainability and extensibility
- Conclusion: **Partial Pass**
- Rationale: some extension points exist, but core business logic is still hard-coded in ways that limit extensibility: export generation is user-table specific, workflow writeback only handles `EXP-` and `APT-`, and governance rollback only restores expense/appointment payloads. `app/services/export_service.py:36-49`, `app/services/process_service.py:11-21`, `app/services/data_governance_service.py:164-177`
- Evidence: `app/services/export_service.py:27-70`, `app/services/process_service.py:11-21`, `app/services/data_governance_service.py:156-191`

### 4. Engineering Details and Professionalism
#### 4.1 Error handling, logging, validation, API design
- Conclusion: **Partial Pass**
- Rationale: there is meaningful input validation and HTTP error usage, but logging is thin and sometimes leaks internal details into immutable audit logs, and some prompt-critical controls are under-enforced or environment-dependent. `app/schemas/auth.py:8-41`, `app/main.py:22-39`, `app/tasks/jobs.py:145-149`, `app/api/v1/audit.py:12-15`
- Evidence: `app/schemas/auth.py:8-41`, `app/core/logging.py:1-18`, `app/tasks/jobs.py:142-167`, `app/api/v1/audit.py:12-15`

#### 4.2 Product/service realism
- Conclusion: **Partial Pass**
- Rationale: the service resembles a real backend, but several flows still read as implementation baseline rather than fully accepted delivery, including fixed reports, limited rollback scope, and missing membership administration surfaces. `README.md:3`, `app/api/v1/metrics.py:22-78`, `app/services/auth_service.py:145-180`
- Evidence: `README.md:3-18`, `app/api/v1/metrics.py:22-78`, `app/services/data_governance_service.py:156-191`

### 5. Prompt Understanding and Requirement Fit
#### 5.1 Business goal, scenario, and constraints
- Conclusion: **Fail**
- Rationale: the project recognizes the requested domains, but the most important constraints are not fully respected: organization isolation is weakened by open registration into existing orgs, attachment ownership checks are bypassed for auditors/admins, HTTPS is not universally enforced, and duplicate-submission/idempotency is not durably guaranteed for same-business-number races. `app/services/auth_service.py:17-21`, `app/services/storage_service.py:137-141`, `app/main.py:24-38`, `app/models/entities.py:96-108`, `app/services/process_service.py:123-138`
- Evidence: `app/services/auth_service.py:16-61`, `app/services/storage_service.py:130-167`, `app/main.py:22-39`, `app/models/entities.py:94-108`, `app/services/process_service.py:123-138`

### 6. Aesthetics
#### 6.1 Frontend visual/interaction quality
- Conclusion: **Not Applicable**
- Rationale: repository is backend-only FastAPI service; no frontend deliverable was present for review.
- Evidence: `README.md:1-57`, `app/main.py:1-48`

## 5. Issues / Suggestions (Severity-Rated)

### Blocker
1. **Open registration can join any existing organization by org code**
- Conclusion: **Fail**
- Evidence: `app/services/auth_service.py:17-21`, `app/services/auth_service.py:41-58`, `app/api/v1/auth.py:13-16`
- Impact: any unauthenticated user who knows an `org_code` can create an account directly inside another tenant, which breaks the prompt’s organization-level isolation and undermines RBAC boundaries.
- Minimum actionable fix: separate “create organization” from “join organization”; require invitation/membership approval for joining existing orgs; reject self-registration into an existing org unless a verified invitation exists.

### High
2. **Attachment object-level authorization is bypassed for auditors and admins**
- Conclusion: **Fail**
- Evidence: `app/services/storage_service.py:137-141`, `app/services/storage_service.py:143-167`
- Impact: the prompt requires attachment access validation by organization and business ownership with unauthorized reads prohibited; current logic grants org-wide read access to all auditors and all admins without business ownership validation.
- Minimum actionable fix: enforce ownership/business-scope checks for every role, with explicit narrowly-scoped exceptions only if the requirement is changed and documented.

3. **HTTPS-only requirement is implemented as environment-dependent, not universal**
- Conclusion: **Fail**
- Evidence: `app/main.py:24-38`, `.env.example:2`
- Impact: default `dev` mode permits plain HTTP despite the prompt stating transmission is HTTPS-only, so the delivered code does not enforce the stated compliance rule by default.
- Minimum actionable fix: enforce HTTPS for all non-local trusted loopback scenarios or fail closed unless an explicit secure reverse-proxy mode is configured and documented.

4. **Duplicate-submission idempotency for same business number is not transaction-safe**
- Conclusion: **Fail**
- Evidence: `app/services/process_service.py:123-138`, `app/models/entities.py:96-108`
- Impact: the prompt requires same business number within 24 hours to return the same processing result, but enforcement is only a pre-insert query; concurrent requests with the same `business_id` can still create duplicates because only `idempotency_key` has a DB uniqueness constraint.
- Minimum actionable fix: add durable database-level protection for the business-number window or serialize instance creation with locking/transaction logic that guarantees single-result behavior.

5. **Scheduler failure compensation max-3-retries is not applied to scheduled jobs generally**
- Conclusion: **Fail**
- Evidence: `app/tasks/jobs.py:14-111`, `app/tasks/jobs.py:112-120`, `app/tasks/jobs.py:172-359`
- Impact: the prompt explicitly requires task scheduling failure compensation with a maximum of 3 retries; only `process_export_job` has retry policy, while backup, metrics, reminders, SLA monitoring, pruning, and timeout jobs do not.
- Minimum actionable fix: define retry policy for each scheduled task or centralize retry handling so scheduled job failures are compensated consistently and capped at three attempts.

6. **Organization join flow is not product-complete and likely breaks the caller’s current token context**
- Conclusion: **Fail**
- Evidence: `app/api/v1/auth.py:49-56`, `app/services/auth_service.py:145-180`, `app/middleware/auth.py:29-33`
- Impact: `join-organization` requires pre-existing membership but no API exists to create/invite memberships, and the method mutates `actor.org_id` while tokens still carry the old `org_id`; subsequent requests with the old token are likely rejected by `get_current_user`.
- Minimum actionable fix: add membership/invitation administration APIs and return a freshly issued token after org-context switching instead of mutating the user record behind an existing token.

### Medium
7. **Operations analysis and reporting are only partially aligned with the prompt**
- Conclusion: **Fail**
- Evidence: `app/api/v1/metrics.py:22-78`, `app/api/v1/hospital.py:14-112`
- Impact: reporting is fixed to dashboard/summary/advanced endpoints with no real customization model, and advanced searches are uneven across appointments/patients/doctors/expenses, so the delivered analysis domain falls short of the requested customizable reporting and richer multi-criteria search capabilities.
- Minimum actionable fix: introduce report definition/query models, richer filter schemas, pagination/sorting contracts, and entity-specific advanced filter support covering the prompt’s target datasets.

8. **Export domain is narrowly implemented for user rows only**
- Conclusion: **Partial Fail**
- Evidence: `app/services/export_service.py:36-49`, `app/api/v1/export.py:17-40`
- Impact: field-whitelist exports exist, but only for `User` data; this materially narrows the prompt’s export requirement for broader operational data domains.
- Minimum actionable fix: generalize export planning and row collection to supported business datasets with per-domain whitelists and desensitization policies.

9. **Data rollback/versioning support is limited to expense and appointment entities**
- Conclusion: **Partial Fail**
- Evidence: `app/services/data_governance_service.py:156-191`
- Impact: the prompt calls for data versioning/snapshots/rollbacks and lineage tracing; lineage exists, but rollback only restores two entity types, leaving broader governance coverage incomplete.
- Minimum actionable fix: introduce typed rollback handlers per governed entity and validate restored payload schemas before commit.

10. **Immutable audit log API can expose internal paths and raw metadata**
- Conclusion: **Partial Fail**
- Evidence: `app/tasks/jobs.py:145-149`, `app/api/v1/audit.py:12-15`
- Impact: completed export audit entries record `output_path`, and `/api/audit/logs` returns raw metadata, exposing internal filesystem details through an immutable log surface.
- Minimum actionable fix: sanitize audit metadata before persistence or filter sensitive/internal fields on retrieval.

11. **Tests are not sufficient for the highest-risk authz/isolation paths**
- Conclusion: **Fail**
- Evidence: `tests/test_audit_remediation.py:67-124`, `tests/test_audit_remediation_v2.py:58-121`, `tests/test_process_routing.py:1-20`
- Impact: severe defects in tenant isolation, attachment ownership, route-level 403s, object-level authorization, and duplicate-submission handling could remain undetected even if the current suite passes.
- Minimum actionable fix: add API tests for cross-tenant registration denial, cross-tenant reads, attachment ownership denial, route 401/403 coverage, org-switch token refresh, and idempotent duplicate submissions.

### Low
12. **Test strategy is inconsistent and partly non-hermetic**
- Conclusion: **Partial Fail**
- Evidence: `tests/conftest.py:11-50`, `tests/test_export_integration.py:11-20`, `tests/test_audit_remediation.py:12-18`
- Impact: some tests use isolated in-memory SQLite while others directly use `SessionLocal`, making static confidence in repeatability lower and increasing drift between environments.
- Minimum actionable fix: standardize tests on isolated fixtures and document the intended test database strategy.

## 6. Security Review Summary
- Authentication entry points: **Partial Pass**. Login/logout/password reset/register exist and password complexity/lockout are implemented. `app/api/v1/auth.py:13-56`, `app/schemas/auth.py:8-41`, `app/services/auth_service.py:64-142`
- Route-level authorization: **Partial Pass**. Most non-auth routes use `require_permission(...)`. `app/api/v1/process.py:13-74`, `app/api/v1/export.py:17-72`, `app/api/v1/data_governance.py:12-43`, `app/api/v1/hospital.py:14-103`
- Object-level authorization: **Fail**. Attachment reads bypass ownership checks for auditors/admins. `app/services/storage_service.py:137-141`
- Function-level authorization: **Partial Pass**. Workflow completion verifies assignee ownership. `app/services/process_service.py:187-194`
- Tenant / user isolation: **Fail**. Cross-org self-registration into an existing org is allowed by org code alone. `app/services/auth_service.py:17-21`, `app/services/auth_service.py:41-58`
- Admin / internal / debug protection: **Partial Pass**. No obvious debug/internal routes were found, but privileged read surfaces like audit logs and attachment reads need tighter object controls. `rg "debug|internal|admin" app`, `app/api/v1/audit.py:12-15`, `app/services/storage_service.py:137-167`

## 7. Tests and Logging Review
- Unit tests: **Partial Pass**. Small unit tests exist for password validation, export masking, and process branch helpers. `tests/test_password_validation.py:1-8`, `tests/test_export_service.py:1-25`, `tests/test_process_routing.py:1-20`
- API / integration tests: **Partial Pass**. Some API tests exist for logout revocation, password reset invalid token, export download, metrics, and lineage RBAC, but coverage is shallow for the highest-risk flows. `tests/test_audit_remediation.py:67-124`, `tests/test_audit_remediation_v2.py:58-121`
- Logging categories / observability: **Partial Pass**. Central logging exists, audit events are persisted, and some warnings/errors are recorded, but categories are sparse and not strongly structured. `app/core/logging.py:1-18`, `app/services/audit_service.py:1-7`
- Sensitive-data leakage risk in logs / responses: **Partial Pass**. Password reset no longer logs reset token, but audit logs still store and expose internal export output paths and raw metadata. `app/services/auth_service.py:120-125`, `app/tasks/jobs.py:145-149`, `app/api/v1/audit.py:12-15`

## 8. Test Coverage Assessment (Static Audit)

### 8.1 Test Overview
- Unit tests exist: yes. `tests/test_password_validation.py:1-8`, `tests/test_export_service.py:1-25`, `tests/test_process_routing.py:1-20`
- API / integration tests exist: yes. `tests/test_audit_remediation.py:67-124`, `tests/test_audit_remediation_v2.py:58-121`, `tests/test_export_integration.py:55-135`
- Frameworks: `pytest`, `fastapi.testclient`. `pyproject.toml:18-23`, `tests/conftest.py:1-50`
- Test entry points: repository `tests/` package; no documented command in README. `tests/`, `README.md:20-57`
- Isolation model: mixed; `tests/conftest.py` uses in-memory SQLite, while some tests use `SessionLocal` directly. `tests/conftest.py:11-50`, `tests/test_export_integration.py:11-20`

### 8.2 Coverage Mapping Table
| Requirement / Risk Point | Mapped Test Case(s) | Key Assertion / Fixture / Mock | Coverage Assessment | Gap | Minimum Test Addition |
|---|---|---|---|---|---|
| Password complexity | `tests/test_password_validation.py:6-8` | Pydantic `RegisterRequest` raises `ValueError` | basically covered | No confirm test for reset-password happy path validation | Add confirm-reset validation tests for valid/invalid passwords |
| Logout token revocation | `tests/test_audit_remediation.py:67-83` | Access after logout returns 401 revoked | basically covered | No route-matrix check beyond `/users/me` | Add 401 checks across multiple protected routes |
| HTTPS enforcement | `tests/test_audit_remediation.py:96-106` | Monkeypatch env to `acceptance`, expect 403 | insufficient | Test proves env-gated behavior, not prompt-required universal enforcement | Add tests for default mode policy and trusted proxy cases |
| Export field whitelist/desensitization | `tests/test_export_service.py:16-25` | Non-admin email stripped, admin may keep email | basically covered | No API-level authorization or cross-org export access tests | Add export API tests for 401/403 and org isolation |
| Export job lifecycle | `tests/test_export_integration.py:55-135` | Job status/audit events asserted; failure path patched | basically covered | Uses direct DB session and does not cover authorization | Add API-driven export create/get/download tests with role constraints |
| Process branch resolution | `tests/test_process_routing.py:4-20` | Branch selection on variables asserted | insufficient | No API/service tests for task completion, parallel signing, SLA/default 48h, idempotency | Add end-to-end process tests for start/approve/reject/quorum/idempotency |
| Password reset invalid token | `tests/test_audit_remediation.py:85-94` | 400 on invalid token | basically covered | No proof of full recovery flow or token expiry behavior | Add request+confirm happy path and expired-token tests |
| Org join authorization | `tests/test_audit_remediation.py:108-124` | Unauthorized join without membership returns 403 | insufficient | Does not cover open registration into existing org or post-join token behavior | Add tests denying cross-org registration and verifying org-switch token refresh |
| Data governance lineage RBAC | `tests/test_audit_remediation_v2.py:114-121` | Admin with read gets 200 | insufficient | No validation/import-batch detail/rollback tests | Add validation, issue writeback, rollback, and tenant isolation tests |
| Tenant / attachment object isolation | None found | None | missing | Severe authz defects could survive | Add cross-tenant and cross-owner read denial tests |

### 8.3 Security Coverage Audit
- Authentication: **Basically covered** for password rules, invalid reset token, and logout revocation; not enough for lockout windows, reset happy path, or org-switch token semantics. `tests/test_password_validation.py:6-8`, `tests/test_audit_remediation.py:67-94`
- Route authorization: **Insufficient**. A few protected route happy paths exist, but there is almost no systematic 401/403 coverage for resources and actions. `tests/test_audit_remediation_v2.py:96-121`
- Object-level authorization: **Missing**. No tests cover attachment ownership or business ownership enforcement.
- Tenant / data isolation: **Missing** for the highest-risk flows. No tests deny registration into an existing org, cross-org export/job access, or cross-org hospital data access.
- Admin / internal protection: **Insufficient**. No tests probe privileged audit/file visibility boundaries.

### 8.4 Final Coverage Judgment
- **Fail**
- Major low-risk utility logic is covered, but the highest-risk defects identified in this audit could still exist while the current tests pass: tenant isolation, object-level authorization, duplicate-submission handling, org-switch behavior, and scheduler retry policy.

## 9. Final Notes
- The repository is a substantial backend codebase, but it does not meet delivery acceptance because core prompt constraints around tenant isolation, object-level access control, HTTPS policy, and durable idempotency are not fully satisfied by the static evidence.
- The strongest remediation priority is security-first: close unauthorized org entry, enforce attachment ownership rules, make HTTPS policy align with the prompt, and harden process idempotency at the persistence layer before expanding feature breadth.
