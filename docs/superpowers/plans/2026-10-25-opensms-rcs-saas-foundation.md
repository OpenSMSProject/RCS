# OpenSMS/RCS SaaS Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce the multi-tenant SaaS foundation—PostgreSQL, PF/PJ tenants, users and RBAC, Super Admin, plans/entitlements, trial state, tenant-scoped API keys and tenant-aware device ownership—without breaking the existing SQLite-backed Remote Connector v1 gateway.

**Architecture:** Keep the current FastAPI gateway, Android protocol, SQLite device/message store and `/api/v1/...` compatibility paths intact while adding a modular SaaS control-plane package backed by PostgreSQL. The control plane and legacy gateway run in the same application process initially but persist independently, so rollout is reversible; later phases bridge canonical messaging state into PostgreSQL. Use a modular monolith, not premature microservices.

**Tech Stack:** Python 3.11, FastAPI 0.128.2, Starlette 0.50.0, Uvicorn 0.48.0, SQLAlchemy 2.1.6, Alembic 1.20.1, psycopg 3.3.6, pwdlib[argon2] 0.3.1, PostgreSQL 16+, pytest, Docker Compose, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-22-opensms-rcs-saas-platform-design.md`

## Global Constraints

- Preserve `GET /healthz`, `GET /readyz`, current Android pairing, WebSocket semantics, ACK/result handling, idempotency, device revocation, current SQLite data, one-command install/update, and the `rcs` command.
- Do not delete or implicitly migrate existing SQLite data in this phase.
- Every tenant-owned SaaS resource must be tenant-scoped server-side.
- Tenant roles are exactly `Owner`, `Admin`, `Operator`; Super Admin is platform-scoped and separate.
- Tenant/document types are exactly `PF/CPF` and `PJ/CNPJ`.
- Default trial: 7 days, 1 device, 200 messages, 2 users, 1 API key, external API enabled, reduced rate limits, panel/history enabled, bulk campaigns disabled.
- One normal trial per normalized CPF/CNPJ; Super Admin may override or extend.
- PF and PJ have separate plan catalogs.
- API keys are tenant-scoped, stored non-recoverably, shown raw only once, and audited on create/revoke.
- Authorization is server-side; UI hiding is not authorization.
- Secrets and message bodies are not logged by default.
- This phase excludes RCS transport, campaigns, billing adapters, DeskCommCRM, and canonical PostgreSQL message storage.

## Review Focus

- Cross-tenant identifier probing must not leak another tenant's users, keys, plans, trials or device mappings.
- Concurrent duplicate CPF/CNPJ signup must not create a second normal trial.
- Admin/Operator must not escalate to Owner or execute Owner-only/platform-only actions.
- Exact trial expiry, suspended tenants and exhausted limits must block only new entitled actions while preserving login/data access.
- PostgreSQL/migration failure must fail SaaS readiness safely without deleting/corrupting the existing SQLite gateway.

---

## File Structure

Create `gateway/opensms_gateway/saas/` with focused modules:

- `config.py` — SaaS/PostgreSQL/session settings.
- `db.py` — SQLAlchemy engine/session lifecycle.
- `models.py` — PostgreSQL ORM entities/enums.
- `security.py` — password/session/API-key primitives.
- `auth.py` — principal resolution and RBAC guards.
- `tenants.py` — signup, verification and membership rules.
- `entitlements.py` — plan/trial evaluation.
- `api_keys.py` — API-key lifecycle.
- `devices.py` — tenant-to-legacy-device bridge.
- `audit.py` — immutable privileged-action audit writes.
- `routes.py` — Phase-1 `/saas/v1/...` HTTP routes.
- `migrations/` — Alembic environment/revisions.

`gateway/opensms_gateway/storage.py` remains the SQLite device/message source of truth throughout Phase 1.

### Task 1: Dependencies, settings and PostgreSQL lifecycle

**Files:**
- Modify: `gateway/requirements.txt`, `gateway/.env.example`
- Create: `gateway/opensms_gateway/saas/__init__.py`, `config.py`, `db.py`
- Test: `tests/saas/test_config.py`, `tests/saas/test_db.py`

**Interfaces:**
- `SaaSSettings.from_env() -> SaaSSettings`
- `create_engine_from_settings(settings: SaaSSettings) -> Engine`
- `session_factory(engine) -> sessionmaker`
- `database_ready(engine) -> bool`

- [ ] Write failing tests: SaaS disabled by default; disabled mode requires no PostgreSQL; enabled mode requires DB URL and strong session secret; DB sessions commit/rollback; readiness returns false on connection failure without touching SQLite.
- [ ] Run `python -m pytest tests/saas/test_config.py tests/saas/test_db.py -v`; expect FAIL.
- [ ] Pin `SQLAlchemy==2.1.6`, `alembic==1.20.1`, `psycopg[binary]==3.3.6`, `pwdlib[argon2]==0.3.1`; implement settings and DB lifecycle.
- [ ] Rerun Task 1 tests; expect PASS.
- [ ] Commit: `feat: add SaaS PostgreSQL foundation`.

### Task 2: PostgreSQL schema and Alembic migration

**Files:**
- Create: `gateway/opensms_gateway/saas/models.py`
- Create: `gateway/opensms_gateway/saas/migrations/alembic.ini`, `env.py`, `script.py.mako`, `versions/0001_saas_foundation.py`
- Test: `tests/saas/test_schema.py`

**Interfaces:**
- Entities: `Tenant`, `User`, `Membership`, `Plan`, `TenantEntitlement`, `Trial`, `ApiKey`, `TenantDevice`, `AuditEvent`, `SessionRecord`, `EmailVerificationToken`.
- `User.is_super_admin: bool` is platform-scoped and never inferred from membership role.
- UUID primary keys; PostgreSQL UUID columns.
- Enums: `TenantType(PF,PJ)`, `DocumentType(CPF,CNPJ)`, `TenantRole(Owner,Admin,Operator)`, `TenantStatus(active,suspended)`, `OveragePolicy(block,bill)`.

- [ ] Write failing schema tests for normalized document uniqueness, membership uniqueness, API-key hash uniqueness, email-verification token uniqueness/expiry fields, tenant-device uniqueness, PF/PJ plan type, Super Admin separation, tenant lookup indexes and safe FK behavior.
- [ ] Run `python -m pytest tests/saas/test_schema.py -v`; expect FAIL.
- [ ] Implement models and `0001_saas_foundation`; exclude billing-provider tables, campaigns, contacts and PostgreSQL messages.
- [ ] Run Alembic `upgrade head` against an empty test DB and rerun schema tests; expect PASS.
- [ ] Commit: `feat: add SaaS tenant schema and migrations`.

### Task 3: Authentication, sessions and RBAC primitives

**Files:**
- Create: `gateway/opensms_gateway/saas/security.py`, `auth.py`
- Test: `tests/saas/test_auth_security.py`

**Interfaces:**
- `hash_password(password: str) -> str`
- `verify_password(password: str, encoded: str) -> bool`
- `new_session_token() -> str`
- `hash_session_token(token: str) -> str`
- `Principal(user_id: UUID, tenant_id: UUID | None, role: TenantRole | None, is_super_admin: bool)`
- `require_role(*roles: TenantRole)` and `require_super_admin()`.

- [ ] Write failing tests for Argon2 passwords, high-entropy non-recoverable session tokens, expiry/revocation, suspended principals, Owner/Admin/Operator boundaries and Super Admin separation.
- [ ] Run `python -m pytest tests/saas/test_auth_security.py -v`; expect FAIL.
- [ ] Implement primitives; MFA/SSO remain deferred.
- [ ] Rerun; expect PASS.
- [ ] Commit: `feat: add SaaS authentication and RBAC primitives`.

### Task 4: PF/PJ signup, email verification and memberships

**Files:**
- Create: `gateway/opensms_gateway/saas/tenants.py`
- Test: `tests/saas/test_tenants.py`

**Interfaces:**
- `normalize_document(document_type: DocumentType, value: str) -> str`
- `provision_trial_tenant(session, *, email: str, password: str, tenant_type: TenantType, document_number: str, display_name: str) -> Tenant`
- `issue_email_verification(session, *, user_id: UUID) -> tuple[EmailVerificationToken, str]`
- `verify_email_token(session, *, raw_token: str) -> User`
- `invite_member(...) -> Membership`
- `change_member_role(...) -> Membership`

- [ ] Write failing tests for PF↔CPF/PJ↔CNPJ validation, punctuation-insensitive normalization, first user becoming Owner, duplicate normalized document conflict under concurrency, verified-email default false, one-time verification token use/expiry, and suspended tenant behavior.
- [ ] Add tests proving Admin/Operator cannot create/promote Owner and no operation can remove/demote the last Owner.
- [ ] Run `python -m pytest tests/saas/test_tenants.py -v`; expect FAIL.
- [ ] Implement service rules. Email delivery adapter is deferred; only secure token lifecycle/state is implemented.
- [ ] Rerun; expect PASS.
- [ ] Commit: `feat: provision PF and PJ tenants with RBAC`.

### Task 5: Plan catalogs, trial and centralized entitlements

**Files:**
- Create: `gateway/opensms_gateway/saas/entitlements.py`
- Test: `tests/saas/test_entitlements.py`

**Interfaces:**
- `EntitlementDecision(allowed: bool, reason: str | None, limit: int | None, used: int | None)`
- `evaluate_entitlement(session, *, tenant_id: UUID, capability: str, now: datetime) -> EntitlementDecision`
- Phase-1 capabilities: `users`, `devices`, `api_keys`, `external_api`, `bulk_campaigns`, `messages`.

- [ ] Write failing trial tests: exactly 7 days; 2 users; 1 device; 1 API key; 200-message allowance represented; external API true; bulk campaigns false; exact expiry behavior; Super Admin extension; one normal trial per document.
- [ ] Write failing plan tests: PF plan cannot be assigned to PJ or vice versa; overage policy stores `block|bill`; centralized decisions apply to creation/actions.
- [ ] Run `python -m pytest tests/saas/test_entitlements.py -v`; expect FAIL.
- [ ] Implement entitlement service; message usage metering remains Phase 2, but message allowance is modeled now.
- [ ] Rerun; expect PASS.
- [ ] Commit: `feat: add SaaS trials plans and entitlements`.

### Task 6: Tenant-scoped API keys

**Files:**
- Create: `gateway/opensms_gateway/saas/api_keys.py`
- Test: `tests/saas/test_api_keys.py`

**Interfaces:**
- `create_api_key(session, *, tenant_id: UUID, actor: Principal, label: str) -> tuple[ApiKey, str]`
- `authenticate_api_key(session, raw_key: str) -> Principal`
- `revoke_api_key(session, *, key_id: UUID, actor: Principal) -> None`
- Prefix: `osms_live_`; store only non-recoverable hash.

- [ ] Write failing lifecycle tests: raw key returned once, unrecoverable storage, trial limit 1, revoke, last-used update, entitlement check, audit event.
- [ ] Add cross-tenant tests: Tenant A cannot list/revoke/probe Tenant B's key metadata.
- [ ] Run `python -m pytest tests/saas/test_api_keys.py -v`; expect FAIL.
- [ ] Implement and rerun; expect PASS.
- [ ] Commit: `feat: add tenant scoped API keys`.

### Task 7: Audit and Super Admin service controls

**Files:**
- Create: `gateway/opensms_gateway/saas/audit.py`
- Test: `tests/saas/test_super_admin.py`

**Interfaces:**
- `record_audit(session, *, actor_user_id: UUID | None, tenant_id: UUID | None, action: str, target_type: str, target_id: str | None, metadata: dict | None = None) -> AuditEvent`
- Super Admin operations: suspend/reactivate tenant, extend trial, change plan, courtesy entitlement override.

- [ ] Write failing tests proving every tenant role is denied platform actions, every Super Admin mutation emits an audit event, and audit metadata contains no credentials/message bodies.
- [ ] Run `python -m pytest tests/saas/test_super_admin.py -v`; expect FAIL.
- [ ] Implement and rerun; expect PASS.
- [ ] Commit: `feat: add audited Super Admin controls`.

### Task 8: Tenant ownership bridge for existing SQLite devices

**Files:**
- Create: `gateway/opensms_gateway/saas/devices.py`
- Test: `tests/saas/test_tenant_devices.py`

**Interfaces:**
- `claim_legacy_device(session, *, tenant_id: UUID, device_id: str, actor: Principal, gateway_store: GatewayStore) -> TenantDevice`
- `list_tenant_devices(session, *, tenant_id: UUID, gateway_store: GatewayStore) -> list[dict]`
- PostgreSQL stores ownership metadata only; credential/live state remain in SQLite in Phase 1.

- [ ] Write failing tests: only existing SQLite device can be claimed; one legacy device cannot belong to two tenants; device entitlement enforced; no credential hash copied to PostgreSQL; cross-tenant lookup denied.
- [ ] Run `python -m pytest tests/saas/test_tenant_devices.py -v`; expect FAIL.
- [ ] Implement without altering `GatewayStore` schema.
- [ ] Run tenant-device plus existing storage/WebSocket tests; expect PASS.
- [ ] Commit: `feat: map legacy devices to SaaS tenants`.

### Task 9: Phase-1 SaaS HTTP routes

**Files:**
- Create: `gateway/opensms_gateway/saas/routes.py`
- Modify: `gateway/opensms_gateway/app.py`
- Test: `tests/saas/test_routes.py`

**Interfaces:**
- New routes live under `/saas/v1/...`; existing `/api/v1/...` is unchanged.
- Route groups: signup/email verification, login/logout/session, current tenant/profile, members, API keys, tenant devices, plans/trial status, Super Admin tenant/plan/trial controls.

- [ ] Write failing route tests for session lifecycle, email verification gate where required, RBAC, Super Admin separation, tenant-scoped lookup, API-key one-time response and secret redaction.
- [ ] Run SaaS routes plus existing API/WebSocket tests; SaaS tests must FAIL before implementation while legacy tests remain PASS.
- [ ] Mount SaaS conditionally via `OPENSMS_SAAS_ENABLED`. Disabled mode must behave exactly like current gateway; enabled mode initializes PostgreSQL and `/saas/v1` without weakening legacy auth.
- [ ] Rerun `python -m pytest tests/saas/test_routes.py tests/gateway -v`; expect PASS.
- [ ] Commit: `feat: expose SaaS foundation API`.

### Task 10: PostgreSQL Compose + migration-safe installer/update

**Files:**
- Modify: `gateway/docker-compose.yml`, `gateway/.env.example`, `install.sh`, `tests/test_install_script.py`
- Create: `tests/saas/test_compose_contract.py`

**Interfaces:**
- Compose service `opensms-postgres`, internal only, persistent volume `opensms-postgres-data`.
- Gateway gets `OPENSMS_SAAS_DATABASE_URL` from `.env`.
- `rcs update` runs `alembic upgrade head` before SaaS is considered ready; it never deletes SQLite/PostgreSQL data.

- [ ] Write failing contract tests: PostgreSQL no host port by default; persistent volume; health dependency; existing `.env` preserved; missing DB/session secrets generated without printing; failed migration stops update safely; current `0.0.0.0:8080:8080`, SQLite permissions and `FINAL_STATUS=PASS` remain.
- [ ] Run contract tests; expect FAIL.
- [ ] Implement Compose/installer changes.
- [ ] Rerun; expect PASS.
- [ ] Commit: `feat: deploy SaaS PostgreSQL safely`.

### Task 11: CI PostgreSQL and isolation regression gates

**Files:**
- Modify: `.github/workflows/test.yml`
- Create: `tests/integration/test_saas_isolation.py`, `tests/integration/test_saas_postgres.py`

- [ ] Add two-tenant negative integration tests for memberships, API keys, device mappings, trial/plan data and platform-only actions.
- [ ] Add migration/readiness tests: clean upgrade, repeated upgrade, healthy DB readiness, unavailable DB failure, SQLite preservation.
- [ ] Add ephemeral PostgreSQL service to CI; run migrations before SaaS integration tests; compile `gateway/opensms_gateway/saas/*.py`.
- [ ] Run `python -m pytest tests -q`; expect PASS. Run `git diff --check`; expect no output.
- [ ] Commit: `test: gate SaaS tenant isolation on PostgreSQL`.

### Task 12: Phase-1 operational docs and acceptance

**Files:**
- Modify: `README.md`, `CHANGELOG.md`
- Create: `docs/saas-foundation.md`

- [ ] Document SaaS enable/disable, migrations, PF/PJ model, roles, trial defaults, API-key one-time display, `rcs` commands, backup/rollback rule and Phase-1 non-goals.
- [ ] Run all tests and compile checks.
- [ ] Explicitly verify legacy `/healthz`, `/readyz`, pairing, WebSocket, ACK/result, SQLite persistence, installer and `rcs` command with SaaS disabled.
- [ ] Commit: `docs: describe SaaS foundation rollout`.

## Phase-1 Done Gate

Phase 1 is complete only when:

- PostgreSQL migrates cleanly from empty state.
- PF/PJ tenants provision with a first Owner and verified-email lifecycle exists.
- Owner/Admin/Operator server-side authorization passes negative tests.
- Super Admin is explicitly platform-scoped and audited.
- Default trial limits/expiry are centrally modeled/enforced.
- PF/PJ plan catalogs are separated.
- API keys are tenant-scoped, one-time-display and non-recoverably stored.
- Existing SQLite devices map to exactly one tenant without moving credentials/deleting SQLite data.
- Cross-tenant negative tests pass.
- Current Android/gateway API/WebSocket tests remain green.
- Installer/`rcs update` preserve existing `.env`, SQLite and PostgreSQL data.
- CI is green.

## Explicitly Deferred

- **Phase 2:** tenant-aware SMS send/history, manual/automatic device routing, usage metering, quota enforcement and tenant dashboard.
- **Phase 3:** contacts/lists, CSV import, campaigns, scheduling and workers.
- **Phase 4:** billing core plus Stripe, Mercado Pago and Cora adapters/webhooks.
- **Phase 5:** optional DeskCommCRM connector/add-on.
- **Later channels:** RCS transport, WhatsApp official/unofficial, Telegram, email and future adapters.
