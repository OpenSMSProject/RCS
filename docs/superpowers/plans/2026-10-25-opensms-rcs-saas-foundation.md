# OpenSMS/RCS SaaS Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce the multi-tenant SaaS foundation—PostgreSQL, PF/PJ tenants, users and RBAC, Super Admin, plans/entitlements, trial state, tenant-scoped API keys and tenant-aware device ownership—without breaking the existing SQLite-backed Remote Connector v1 gateway.

**Architecture:** Keep the current FastAPI gateway, Android protocol, SQLite device/message store and `/api/v1/...` compatibility paths intact while adding a modular SaaS control-plane package backed by PostgreSQL. The control plane and existing gateway run in the same application process initially, but persist independently so rollout is reversible; later phases bridge canonical messaging state into PostgreSQL. Use a modular monolith, not premature microservices.

**Tech Stack:** Python 3.11, FastAPI 0.128.2, Starlette 0.50.0, Uvicorn 0.48.0, SQLAlchemy 2.1.6, Alembic 1.20.1, psycopg 3.3.6, pwdlib[argon2] 0.3.1, PostgreSQL 16+, pytest, Docker Compose, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-22-opensms-rcs-saas-platform-design.md`

## Global Constraints

- Preserve `GET /healthz`, `GET /readyz`, current Android pairing, WebSocket connection semantics, ACK/result handling, idempotency, device revocation, the current SQLite data, one-command install/update philosophy, and the `rcs` management command.
- Do not delete or implicitly migrate existing SQLite data in this phase.
- Every tenant-owned SaaS entity must carry `tenant_id` or be reachable only through an explicitly tenant-scoped parent relation.
- Tenant roles are exactly `Owner`, `Admin`, and `Operator`; Super Admin is platform-scoped and separate from tenant roles.
- Supported tenant types are exactly `PF` and `PJ`; document types are exactly `CPF` and `CNPJ`.
- Default trial is 7 days, 1 device, 200 messages, up to 2 users, 1 API key, external API enabled, reduced rate limits, panel/history enabled, and bulk campaigns disabled.
- One normal trial per CPF or CNPJ; Super Admin may override or extend it.
- PF and PJ use distinct plan catalogs.
- API keys are tenant-scoped, stored non-recoverably, shown raw only once at creation, and auditable on create/revoke.
- Authorization is enforced server-side. UI hiding is never authorization.
- Secrets and message bodies must not be logged by default.
- This phase does not implement RCS transport, campaigns, billing provider adapters, DeskCommCRM integration, or canonical PostgreSQL messaging storage.

## Review Focus

- Cross-tenant identifier probing: requesting another tenant's user, API key, plan assignment or device mapping must behave as not found/forbidden without leaking existence.
- Duplicate CPF/CNPJ signup: the same normalized document must not receive a second normal trial even under concurrent requests.
- Role escalation: Admin/Operator must not be able to assign themselves Owner or perform Owner-only operations through direct API calls.
- Trial boundary conditions: exact expiry instant, suspended tenants, and exhausted trial device/API-key/user limits must block only new entitled actions while preserving login and data access.
- PostgreSQL outage/migration failure: `/readyz` must report the SaaS dependency state without corrupting or deleting the existing SQLite gateway database, and rollback must remain possible.

---

## File Structure

Create a focused SaaS package under the existing gateway package:

- `gateway/opensms_gateway/saas/config.py` — SaaS/PostgreSQL/session settings.
- `gateway/opensms_gateway/saas/db.py` — SQLAlchemy engine/session lifecycle.
- `gateway/opensms_gateway/saas/models.py` — PostgreSQL ORM entities/enums.
- `gateway/opensms_gateway/saas/security.py` — password, session and API-key primitives.
- `gateway/opensms_gateway/saas/auth.py` — authenticated principal resolution and RBAC guards.
- `gateway/opensms_gateway/saas/tenants.py` — tenant provisioning/membership rules.
- `gateway/opensms_gateway/saas/entitlements.py` — plan/trial limit evaluation.
- `gateway/opensms_gateway/saas/api_keys.py` — API-key lifecycle.
- `gateway/opensms_gateway/saas/devices.py` — tenant-to-existing-device ownership bridge.
- `gateway/opensms_gateway/saas/audit.py` — immutable audit event writes.
- `gateway/opensms_gateway/saas/routes.py` — Phase-1 HTTP routes only.
- `gateway/opensms_gateway/saas/migrations/` — Alembic environment and revisions.

Keep `gateway/opensms_gateway/storage.py` as the existing SQLite gateway source of truth during this phase.

### Task 1: Add SaaS dependencies, settings and PostgreSQL session lifecycle

**Files:**
- Modify: `gateway/requirements.txt`
- Modify: `gateway/.env.example`
- Create: `gateway/opensms_gateway/saas/__init__.py`
- Create: `gateway/opensms_gateway/saas/config.py`
- Create: `gateway/opensms_gateway/saas/db.py`
- Create: `tests/saas/test_config.py`
- Create: `tests/saas/test_db.py`

**Interfaces:**
- Produces: `SaaSSettings.from_env() -> SaaSSettings`
- Produces: `create_engine_from_settings(settings: SaaSSettings) -> sqlalchemy.Engine`
- Produces: `session_factory(engine) -> sessionmaker`
- Produces: `database_ready(engine) -> bool`

- [ ] **Step 1: Write failing configuration tests**

Assert `OPENSMS_SAAS_DATABASE_URL` is required when SaaS is enabled, `OPENSMS_SAAS_ENABLED` defaults to `0`, secure session-secret validation rejects empty/short values, and disabled SaaS does not require PostgreSQL credentials.

- [ ] **Step 2: Run configuration tests and verify failure**

Run: `python -m pytest tests/saas/test_config.py -v`
Expected: FAIL because the SaaS package does not exist.

- [ ] **Step 3: Add pinned runtime dependencies and implement settings**

Add `SQLAlchemy==2.1.6`, `alembic==1.20.1`, `psycopg[binary]==3.3.6`, and `pwdlib[argon2]==0.3.1`. Add env examples for SaaS enablement, PostgreSQL URL and session secret without changing existing gateway variables.

- [ ] **Step 4: Write and run failing DB lifecycle tests**

Use a test database fixture; assert sessions commit/rollback correctly and `database_ready()` returns false on connection failure without touching SQLite.

Run: `python -m pytest tests/saas/test_db.py -v`
Expected: FAIL before implementation.

- [ ] **Step 5: Implement DB lifecycle and rerun Task 1 tests**

Run: `python -m pytest tests/saas/test_config.py tests/saas/test_db.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add gateway/requirements.txt gateway/.env.example gateway/opensms_gateway/saas tests/saas/test_config.py tests/saas/test_db.py
git commit -m "feat: add SaaS PostgreSQL foundation"
```

### Task 2: Define the Phase-1 PostgreSQL schema and Alembic migration

**Files:**
- Create: `gateway/opensms_gateway/saas/models.py`
- Create: `gateway/opensms_gateway/saas/migrations/alembic.ini`
- Create: `gateway/opensms_gateway/saas/migrations/env.py`
- Create: `gateway/opensms_gateway/saas/migrations/script.py.mako`
- Create: `gateway/opensms_gateway/saas/migrations/versions/0001_saas_foundation.py`
- Create: `tests/saas/test_schema.py`

**Interfaces:**
- Produces ORM entities: `Tenant`, `User`, `Membership`, `Plan`, `TenantEntitlement`, `Trial`, `ApiKey`, `TenantDevice`, `AuditEvent`, `SessionRecord`.
- Tenant IDs and entity IDs are UUIDs stored as PostgreSQL UUID columns.
- Canonical enums: `TenantType(PF,PJ)`, `DocumentType(CPF,CNPJ)`, `TenantRole(Owner,Admin,Operator)`, `TenantStatus(active,suspended)`, `OveragePolicy(block,bill)`.

- [ ] **Step 1: Write failing schema tests**

Assert normalized `document_number` uniqueness, one membership per user/tenant, one Owner minimum enforced by service rules, API-key hash uniqueness, tenant-device uniqueness, PF/PJ plan type, indexes on tenant-scoped lookup columns, and foreign-key delete behavior that never cascades tenant deletion into the legacy SQLite database.

- [ ] **Step 2: Run schema tests and verify failure**

Run: `python -m pytest tests/saas/test_schema.py -v`
Expected: FAIL because models/migration do not exist.

- [ ] **Step 3: Implement models and migration**

Keep billing-provider tables, campaigns, contacts and PostgreSQL messages out of `0001`.

- [ ] **Step 4: Verify migration round-trip on an empty test database**

Run: `alembic -c gateway/opensms_gateway/saas/migrations/alembic.ini upgrade head`
Expected: migration reaches `0001_saas_foundation`.

Run: `python -m pytest tests/saas/test_schema.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gateway/opensms_gateway/saas/models.py gateway/opensms_gateway/saas/migrations tests/saas/test_schema.py
git commit -m "feat: add SaaS tenant schema and migrations"
```

### Task 3: Implement password hashing, sessions and authenticated principals

**Files:**
- Create: `gateway/opensms_gateway/saas/security.py`
- Create: `gateway/opensms_gateway/saas/auth.py`
- Create: `tests/saas/test_auth_security.py`

**Interfaces:**
- Produces: `hash_password(password: str) -> str`
- Produces: `verify_password(password: str, encoded: str) -> bool`
- Produces: `new_session_token() -> str`
- Produces: `hash_session_token(token: str) -> str`
- Produces: `Principal(user_id: UUID, tenant_id: UUID | None, role: TenantRole | None, is_super_admin: bool)`
- Produces: `require_role(*roles: TenantRole)` and `require_super_admin()` FastAPI dependencies.

- [ ] **Step 1: Write failing security tests**

Cover Argon2 password hashes, invalid password rejection, high-entropy session tokens, non-recoverable stored session tokens, expiry/revocation, and no password/session secret in exception strings.

- [ ] **Step 2: Write failing RBAC tests**

Assert Owner > Admin > Operator capabilities exactly as the spec defines, Super Admin is not synthesized from a tenant role, and direct dependency calls reject missing/suspended principals.

- [ ] **Step 3: Run tests and verify failure**

Run: `python -m pytest tests/saas/test_auth_security.py -v`
Expected: FAIL.

- [ ] **Step 4: Implement minimal security/auth primitives**

Do not implement MFA/SSO in this phase.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/saas/test_auth_security.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add gateway/opensms_gateway/saas/security.py gateway/opensms_gateway/saas/auth.py tests/saas/test_auth_security.py
git commit -m "feat: add SaaS authentication and RBAC primitives"
```

### Task 4: Implement PF/PJ tenant provisioning, memberships and verified-email state

**Files:**
- Create: `gateway/opensms_gateway/saas/tenants.py`
- Create: `tests/saas/test_tenants.py`

**Interfaces:**
- Produces: `normalize_document(document_type: DocumentType, value: str) -> str`
- Produces: `provision_trial_tenant(session, *, email: str, password: str, tenant_type: TenantType, document_number: str, display_name: str) -> Tenant`
- Produces: `invite_member(session, *, tenant_id: UUID, actor: Principal, email: str, role: TenantRole) -> Membership`
- Produces: `change_member_role(session, *, membership_id: UUID, actor: Principal, role: TenantRole) -> Membership`
- First provisioned user becomes `Owner`.

- [ ] **Step 1: Write failing provisioning tests**

Cover PF↔CPF and PJ↔CNPJ pairing, punctuation-insensitive document normalization, first Owner creation, duplicate normalized document conflict, duplicate email behavior, verified-email flag defaulting false, and suspended tenant login/action rules.

- [ ] **Step 2: Add role-escalation and last-Owner tests**

Admin/Operator cannot create/promote an Owner; no operation may remove/demote the last Owner.

- [ ] **Step 3: Run tests and verify failure**

Run: `python -m pytest tests/saas/test_tenants.py -v`
Expected: FAIL.

- [ ] **Step 4: Implement tenant/membership service rules**

Email delivery itself remains adapter work; this task stores verified-email state and one-time verification-token hash records only.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/saas/test_tenants.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add gateway/opensms_gateway/saas/tenants.py tests/saas/test_tenants.py
git commit -m "feat: provision PF and PJ tenants with RBAC"
```

### Task 5: Implement plan catalogs, trial state and centralized entitlement evaluation

**Files:**
- Create: `gateway/opensms_gateway/saas/entitlements.py`
- Create: `tests/saas/test_entitlements.py`

**Interfaces:**
- Produces: `EntitlementDecision(allowed: bool, reason: str | None, limit: int | None, used: int | None)`
- Produces: `evaluate_entitlement(session, *, tenant_id: UUID, capability: str, now: datetime) -> EntitlementDecision`
- Capabilities in Phase 1: `users`, `devices`, `api_keys`, `external_api`, `bulk_campaigns`.
- Default trial limits: users=2, devices=1, api_keys=1, messages=200; external_api=true; bulk_campaigns=false; duration=7 days.

- [ ] **Step 1: Write failing trial tests**

Assert trial starts once per normalized document, exact 7-day expiry, Super Admin extension, expired trial preserves login/data but blocks entitled creation, and trial does not imply automatic billing.

- [ ] **Step 2: Write failing plan tests**

Assert PF plan cannot be assigned to PJ and vice versa, hard-block vs bill-overage is stored, and entitlement evaluation is centralized rather than route-specific.

- [ ] **Step 3: Run tests and verify failure**

Run: `python -m pytest tests/saas/test_entitlements.py -v`
Expected: FAIL.

- [ ] **Step 4: Implement entitlement service**

Do not implement paid-provider synchronization or message metering yet; provide the interfaces later phases will consume.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/saas/test_entitlements.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add gateway/opensms_gateway/saas/entitlements.py tests/saas/test_entitlements.py
git commit -m "feat: add SaaS trials plans and entitlements"
```

### Task 6: Add tenant-scoped API keys

**Files:**
- Create: `gateway/opensms_gateway/saas/api_keys.py`
- Create: `tests/saas/test_api_keys.py`

**Interfaces:**
- Produces: `create_api_key(session, *, tenant_id: UUID, actor: Principal, label: str) -> tuple[ApiKey, str]`
- Produces: `authenticate_api_key(session, raw_key: str) -> Principal`
- Produces: `revoke_api_key(session, *, key_id: UUID, actor: Principal) -> None`
- Raw key prefix: `osms_live_`; store only a keyed/non-recoverable hash.

- [ ] **Step 1: Write failing lifecycle tests**

Assert raw key is returned once, stored representation cannot recover the raw key, trial key limit is 1, revoked keys fail authentication, `last_used_at` updates, and key labels/metadata are tenant-scoped.

- [ ] **Step 2: Add cross-tenant negative tests**

Tenant A cannot list/revoke/authenticate against Tenant B metadata by identifier probing.

- [ ] **Step 3: Run tests and verify failure**

Run: `python -m pytest tests/saas/test_api_keys.py -v`
Expected: FAIL.

- [ ] **Step 4: Implement API-key service and rerun tests**

Run: `python -m pytest tests/saas/test_api_keys.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gateway/opensms_gateway/saas/api_keys.py tests/saas/test_api_keys.py
git commit -m "feat: add tenant scoped API keys"
```

### Task 7: Add auditable Super Admin operations

**Files:**
- Create: `gateway/opensms_gateway/saas/audit.py`
- Create: `tests/saas/test_super_admin.py`

**Interfaces:**
- Produces: `record_audit(session, *, actor_user_id: UUID | None, tenant_id: UUID | None, action: str, target_type: str, target_id: str | None, metadata: dict | None = None) -> AuditEvent`
- Produces Super Admin service methods for suspend/reactivate tenant, extend trial, change plan and courtesy entitlement override.

- [ ] **Step 1: Write failing Super Admin authorization tests**

Tenant Owner/Admin/Operator must all fail platform-only actions. Super Admin actions must create audit events containing actor, action, target and timestamp but never credentials/message bodies.

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/saas/test_super_admin.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement audit helper and Super Admin service methods**

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/saas/test_super_admin.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gateway/opensms_gateway/saas/audit.py tests/saas/test_super_admin.py
git commit -m "feat: add audited Super Admin controls"
```

### Task 8: Add tenant ownership bridge for existing SQLite devices

**Files:**
- Create: `gateway/opensms_gateway/saas/devices.py`
- Create: `tests/saas/test_tenant_devices.py`

**Interfaces:**
- Produces: `claim_legacy_device(session, *, tenant_id: UUID, device_id: str, actor: Principal, gateway_store: GatewayStore) -> TenantDevice`
- Produces: `list_tenant_devices(session, *, tenant_id: UUID, gateway_store: GatewayStore) -> list[dict]`
- PostgreSQL stores ownership/tenant metadata only; device credential and live online state remain in the existing SQLite `GatewayStore` in Phase 1.

- [ ] **Step 1: Write failing bridge tests**

Assert only an existing SQLite device can be claimed, one legacy `device_id` cannot belong to two tenants, entitlement device limit is enforced, credential hashes never enter PostgreSQL through this bridge, and Tenant A cannot inspect Tenant B's mapped device.

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/saas/test_tenant_devices.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement bridge**

Do not alter `GatewayStore` schema in this task.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/saas/test_tenant_devices.py tests/gateway/test_storage.py tests/gateway/test_websocket.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gateway/opensms_gateway/saas/devices.py tests/saas/test_tenant_devices.py
git commit -m "feat: map legacy devices to SaaS tenants"
```

### Task 9: Expose Phase-1 SaaS HTTP routes without changing legacy API semantics

**Files:**
- Create: `gateway/opensms_gateway/saas/routes.py`
- Modify: `gateway/opensms_gateway/app.py`
- Create: `tests/saas/test_routes.py`

**Interfaces:**
- Adds `/saas/v1/...` routes only; existing `/api/v1/...` remains unchanged in Phase 1.
- Minimum route groups: auth/session, current tenant/profile, members, API keys, tenant devices, plans/trial status, Super Admin tenant/plan/trial controls.

- [ ] **Step 1: Write failing route tests**

Cover login/session expiry, verified-email state, Owner/Admin/Operator authorization, Super Admin separation, tenant-scoped lookup behavior, API-key one-time response, and no raw secret in list/detail payloads.

- [ ] **Step 2: Add regression tests for legacy routes**

Assert all current gateway route paths and response semantics used by existing tests remain green.

- [ ] **Step 3: Run tests and verify failure**

Run: `python -m pytest tests/saas/test_routes.py tests/gateway/test_api.py tests/gateway/test_websocket.py -v`
Expected: SaaS tests FAIL before implementation; legacy tests remain PASS.

- [ ] **Step 4: Mount SaaS routes conditionally**

When `OPENSMS_SAAS_ENABLED=0`, the gateway must behave as the current installation does. When enabled, initialize PostgreSQL dependencies and mount `/saas/v1` routes without weakening legacy authentication.

- [ ] **Step 5: Run Task 9 tests**

Run: `python -m pytest tests/saas/test_routes.py tests/gateway -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add gateway/opensms_gateway/saas/routes.py gateway/opensms_gateway/app.py tests/saas/test_routes.py
git commit -m "feat: expose SaaS foundation API"
```

### Task 10: Add PostgreSQL to Docker Compose and make installer/update migration-safe

**Files:**
- Modify: `gateway/docker-compose.yml`
- Modify: `gateway/.env.example`
- Modify: `install.sh`
- Modify: `tests/test_install_script.py`
- Create: `tests/saas/test_compose_contract.py`

**Interfaces:**
- Compose service: `opensms-postgres` with persistent named volume `opensms-postgres-data`.
- Gateway receives `OPENSMS_SAAS_DATABASE_URL` via `.env`.
- `rcs update` runs `alembic upgrade head` before considering SaaS ready, but never deletes SQLite or PostgreSQL data.

- [ ] **Step 1: Write failing installer/compose contract tests**

Assert PostgreSQL is internal-only (no host port by default), persistent volume exists, gateway waits for DB health when SaaS enabled, installer preserves an existing `.env`, generates missing DB/session credentials without printing them, and update fails safely when migration fails.

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_install_script.py tests/saas/test_compose_contract.py -v`
Expected: FAIL against current Compose/installer.

- [ ] **Step 3: Implement Compose and installer changes**

Preserve current `0.0.0.0:8080:8080`, SQLite data directory ownership, `rcs status|update|restart|logs`, and `FINAL_STATUS=PASS` contract. Add PostgreSQL/SaaS status fields only when enabled.

- [ ] **Step 4: Run contract tests**

Run: `python -m pytest tests/test_install_script.py tests/saas/test_compose_contract.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gateway/docker-compose.yml gateway/.env.example install.sh tests/test_install_script.py tests/saas/test_compose_contract.py
git commit -m "feat: deploy SaaS PostgreSQL safely"
```

### Task 11: Add CI PostgreSQL integration and exhaustive tenant-isolation regression gates

**Files:**
- Modify: `.github/workflows/test.yml`
- Create: `tests/integration/test_saas_isolation.py`
- Create: `tests/integration/test_saas_postgres.py`

**Interfaces:**
- CI PostgreSQL service with a dedicated ephemeral database.
- Test env enables SaaS only for SaaS/integration tests.

- [ ] **Step 1: Write cross-tenant integration tests**

Create two tenants and prove negative access for memberships, API keys, tenant-device mappings, plans/trial state and Super Admin-only operations.

- [ ] **Step 2: Write migration/readiness integration tests**

Assert clean `upgrade head`, repeated upgrade idempotence, application readiness with healthy PostgreSQL, expected readiness failure with unavailable SaaS DB, and unchanged SQLite legacy gateway data across migration runs.

- [ ] **Step 3: Update CI workflow**

Add PostgreSQL service, compile the new SaaS package recursively, run migrations, then run all tests.

- [ ] **Step 4: Run full local suite**

Run: `python -m pytest tests -q`
Expected: PASS.

Run: `python -m py_compile gateway/opensms_gateway/*.py gateway/opensms_gateway/saas/*.py gateway/run.py`
Expected: exit 0.

Run: `git diff --check`
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/test.yml tests/integration/test_saas_isolation.py tests/integration/test_saas_postgres.py
git commit -m "test: gate SaaS tenant isolation on PostgreSQL"
```

### Task 12: Phase-1 acceptance and documentation

**Files:**
- Modify: `README.md`
- Create: `docs/saas-foundation.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Documents local single-node SaaS enablement, env variables, migration/rollback rules, default trial, PF/PJ roles, API-key one-time display behavior and explicit Phase-1 non-goals.

- [ ] **Step 1: Document operational runbook**

Include `rcs status`, `rcs update`, PostgreSQL backup prerequisite before destructive future migrations, and how to disable SaaS without removing the legacy gateway.

- [ ] **Step 2: Run full acceptance suite**

Run: `python -m pytest tests -q`
Expected: PASS.

Run: `git diff --check`
Expected: no output.

- [ ] **Step 3: Verify legacy gateway compatibility explicitly**

Run the current gateway tests with SaaS disabled and confirm `/healthz`, `/readyz`, pairing, device WebSocket, message ACK/result, SQLite persistence and installer contract remain green.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/saas-foundation.md CHANGELOG.md
git commit -m "docs: describe SaaS foundation rollout"
```

## Phase-1 Done Gate

Phase 1 is complete only when all of the following are true:

- PostgreSQL migrations pass from an empty database.
- PF and PJ tenants can be provisioned with a first Owner.
- Owner/Admin/Operator server-side authorization tests pass.
- Super Admin is platform-scoped and auditable.
- Default 7-day trial and its exact limits are enforced centrally.
- PF/PJ plan catalogs are separated.
- Tenant-scoped API keys are one-time-display and non-recoverably stored.
- Existing SQLite devices can be mapped to exactly one tenant without moving credentials or deleting SQLite data.
- Cross-tenant negative tests pass.
- Current Android/gateway API/WebSocket tests still pass unchanged.
- `install.sh` and `rcs update` remain idempotent and preserve existing `.env`, SQLite and PostgreSQL data.
- CI is green.

## Explicitly Deferred to Later Plans

- **Phase 2:** tenant-aware SMS send/history, manual/automatic device routing, usage metering, quota enforcement and tenant dashboard.
- **Phase 3:** contacts/lists, CSV import, campaigns, scheduling and workers.
- **Phase 4:** provider-independent billing plus Stripe, Mercado Pago and Cora adapters/webhooks.
- **Phase 5:** optional DeskCommCRM connector/add-on.
- **Later channel plans:** RCS transport, WhatsApp official/unofficial, Telegram, email and other adapters.
