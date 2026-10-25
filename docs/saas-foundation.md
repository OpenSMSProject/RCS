# OpenSMS/RCS SaaS Foundation — Phase 1

This document describes the Phase 1 multi-tenant SaaS control plane introduced alongside the existing Remote Connector v1 gateway.

## Safety boundary

Phase 1 does **not** replace the existing SQLite gateway database. Existing Android pairing, device credentials, WebSocket sessions, SMS job state, ACK/result handling, idempotency and device revocation remain owned by the current gateway/SQLite path.

PostgreSQL is introduced in parallel for SaaS control-plane state. Existing SQLite data is not deleted or implicitly migrated.

## Enablement

The gateway reads these settings from `gateway/.env`:

```text
OPENSMS_SAAS_ENABLED=1
OPENSMS_POSTGRES_PASSWORD=<generated secret>
OPENSMS_SAAS_DATABASE_URL=postgresql+psycopg://opensms:<password>@opensms-postgres:5432/opensms
OPENSMS_SAAS_SESSION_SECRET=<generated secret>
```

The one-command installer generates missing PostgreSQL/session secrets without printing them. Existing `.env` values are preserved.

When SaaS is disabled, `/saas/v1/...` is not mounted and the existing gateway behavior remains available.

## Persistence

- Existing gateway/device/message state: SQLite at the existing `OPENSMS_DB_PATH`.
- SaaS control plane: PostgreSQL 16.
- PostgreSQL Compose service: `opensms-postgres`.
- PostgreSQL persistent volume: `opensms-postgres-data`.
- PostgreSQL is not published on a host port by the production Compose file.

The installer and `rcs update` run the Alembic migration before the gateway is considered ready. A failed migration stops the update; it does not delete either SQLite or PostgreSQL data.

## Tenant model

Tenant types are intentionally separate:

- `PF` — individual / CPF.
- `PJ` — company / CNPJ.

CPF/CNPJ are normalized before storage. One normalized document can receive one normal trial. PF and PJ have separate plan catalogs.

## Roles

Tenant roles:

- `Owner` — tenant ownership and sensitive tenant administration.
- `Admin` — operational administration, without Owner-only escalation authority.
- `Operator` — messaging/device visibility operations without sensitive user/key administration.

`Super Admin` is platform-scoped and is **not** a tenant role. Platform mutations are audited.

Authorization is enforced server-side. UI hiding is never treated as authorization.

## Default trial

The Phase 1 default trial is:

- duration: 7 days;
- users: 2;
- devices: 1;
- API keys: 1;
- message allowance modeled: 200;
- external API: enabled;
- bulk campaigns: disabled.

At the exact trial expiry instant, new entitled actions are denied. Login/data retention is separate from entitlement enforcement. Message usage metering and paid overage enforcement are Phase 2/4 work respectively.

Super Admin can extend a trial and apply courtesy entitlement overrides; those actions are audited.

## Authentication

- Passwords use Argon2 through `pwdlib`.
- Browser/API session tokens are high-entropy random values; only their SHA-256 digest is stored.
- Session expiry and revocation are enforced server-side.
- Suspended tenant principals cannot pass tenant role guards.
- Email verification is modeled with one-time, expiring token records.

### Email delivery status

Phase 1 creates and validates email-verification tokens, but **does not yet include a production email-delivery provider adapter**. The signup route records verification-required state and creates the token lifecycle, but public self-service signup must not be launched until an email adapter delivers the raw verification link/token to the intended mailbox. Raw verification tokens are not returned from signup.

## API keys

Tenant API keys:

- start with `osms_live_`;
- are displayed raw only in the create response;
- are stored only as a non-recoverable SHA-256 digest;
- have tenant-scoped metadata;
- track `last_used_at`;
- can be revoked;
- create/revoke operations are audited;
- are limited by trial/plan entitlements.

No endpoint lists or recovers the raw key after creation.

## Existing Android devices

Phase 1 can claim an existing SQLite device into a SaaS tenant:

```text
PostgreSQL TenantDevice
    -> device_id only
    -> existing SQLite GatewayStore device
```

PostgreSQL stores ownership metadata only. It does not copy the device credential hash or move live connection state. A legacy device can belong to only one tenant.

## HTTP API

Phase 1 SaaS routes are isolated under:

```text
/saas/v1/...
```

They include foundation flows for:

- signup and email verification;
- login/logout/session profile;
- members and tenant roles;
- API-key lifecycle;
- claiming/listing existing devices;
- PF/PJ plan listing and trial status;
- Super Admin tenant suspension/reactivation, plan change, trial extension and courtesy entitlements.

Existing `/api/v1/...`, `/healthz`, `/readyz` and `/api/v1/device/connect` contracts remain separate.

## Readiness

`GET /readyz` continues to validate SQLite. When SaaS is enabled, it also validates PostgreSQL. A PostgreSQL outage therefore causes readiness failure without deleting or rewriting the legacy SQLite database.

## Operations

```bash
rcs status
rcs update
rcs restart
rcs logs
```

`rcs status` reports both the gateway and PostgreSQL container state after Phase 1 deployment.

Update order:

1. fetch/fast-forward the approved feature branch;
2. preserve SQLite data and `.env`;
3. start/check PostgreSQL;
4. build the gateway image;
5. run `alembic upgrade head`;
6. only after migration success, start/rebuild the stack;
7. require both `/healthz` and `/readyz` to pass.

## Backup / rollback rule

Before public rollout, backups must cover both:

- `gateway/data/` (legacy SQLite data);
- PostgreSQL volume/database.

A code rollback must not perform a destructive database downgrade automatically. The initial migration intentionally disables destructive downgrade behavior.

## Phase 1 non-goals

Not implemented in this phase:

- canonical SMS message storage in PostgreSQL;
- tenant-aware SMS send/history and automatic device routing;
- message usage metering and quota consumption;
- campaigns/contacts/scheduling;
- Stripe, Mercado Pago or Cora billing adapters;
- DeskCommCRM connector;
- RCS transport;
- WhatsApp official/unofficial adapters;
- production email-delivery adapter;
- MFA/SSO;
- production web admin UI.

Those remain later phases of the SaaS design.
