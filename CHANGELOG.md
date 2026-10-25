# App Details

## Changes

### Unreleased — SaaS Foundation Phase 1
- Add parallel PostgreSQL 16 SaaS control-plane persistence while preserving the existing SQLite Remote Gateway data path.
- Add PF/CPF and PJ/CNPJ tenants with Owner/Admin/Operator RBAC and platform-scoped Super Admin controls.
- Add Argon2 password hashing, hashed sessions, one-time email-verification token lifecycle and audited privileged operations.
- Add separate PF/PJ plan catalogs, 7-day trial defaults and centralized entitlement evaluation.
- Add tenant-scoped API keys with one-time raw display, hash-only storage, revocation and audit events.
- Add safe ownership mapping from SaaS tenants to existing SQLite Android devices without copying device credentials.
- Add `/saas/v1/...` foundation APIs and conditional SaaS mounting without changing legacy `/api/v1/...` contracts.
- Add PostgreSQL Compose service, persistent volume, Alembic migrations, readiness checks and migration-safe installer/`rcs update` behavior.
- Add PostgreSQL/tenant-isolation CI gates.
- Billing providers, campaigns, canonical PostgreSQL messaging, DeskCommCRM, RCS transport, WhatsApp adapters and production email delivery remain deferred.

### 0.1.0
- App will check if required permissions are granted
- Adding logging for API requests
- Fixing the android bottom padding
- Adding a back button

### 0.0.1
- Initial version
