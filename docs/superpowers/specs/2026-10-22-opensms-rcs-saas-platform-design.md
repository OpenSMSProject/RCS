# OpenSMS/RCS SaaS Platform — Design Specification

Date: 2026-10-22
Branch: `feature/remote-connector-v1`
Status: Proposed for implementation after user review
Supersedes: `2026-10-21-opensms-rcs-web-admin-design.md` as the primary product architecture

## 1. Product Goal

Evolve the existing OpenSMS/RCS Gateway from a single-install administrative gateway into a multi-tenant SaaS communications platform.

The platform must support individuals and companies, multiple users per tenant, multiple Android devices, API access, subscription plans, trial, usage accounting, billing integrations, transactional messaging, campaigns, and multiple communication channels.

The existing Remote Connector v1 remains the first transport foundation. SMS is the first production channel. RCS remains a first-class target channel and the architecture must be channel-agnostic from the start.

The SaaS must preserve the current gateway contracts while the control plane is introduced incrementally.

## 2. Product Model

### 2.1 Tenant types

A tenant is the primary isolation and billing boundary.

Supported tenant types:

- `PF` — individual registered with CPF.
- `PJ` — company registered with CNPJ.

Canonical fields:

- `tenant_id`
- `tenant_type = PF | PJ`
- `document_type = CPF | CNPJ`
- `document_number`
- display/legal name
- billing profile
- status
- plan/subscription state
- trial state

CPF and CNPJ plans are distinct product catalogs.

### 2.2 Users and RBAC

Every tenant may have multiple users.

Roles:

- `Owner` — full tenant control; users, devices, API keys, settings, plan/billing, tenant lifecycle.
- `Admin` — operational administration without tenant transfer/deletion authority.
- `Operator` — messaging operations, history, campaigns and device visibility without sensitive credential or user-management access.

Authorization must be enforced server-side. UI hiding alone is never sufficient.

### 2.3 Super Admin

A platform-level Super Admin is separate from tenant roles.

Capabilities include:

- create/suspend/reactivate tenants;
- inspect platform health;
- manage PF/PJ plan catalogs;
- adjust limits and entitlements;
- extend or grant trial manually;
- apply courtesy credits;
- change tenant plan;
- inspect aggregate usage;
- investigate operational failures with auditable access;
- manage billing provider configuration;
- manage channel/provider availability.

Super Admin must not casually expose tenant message content or credentials. Privileged support access must be auditable.

## 3. Tenant Isolation

Every tenant-owned resource must carry `tenant_id` and every tenant query must be scoped by authenticated tenant context.

Tenant-scoped entities include at minimum:

- users/memberships;
- devices;
- device credentials;
- API keys;
- messages;
- campaigns;
- usage records;
- billing/subscription records;
- contacts/lists required for campaigns;
- channel connectors;
- integrations;
- webhook endpoints;
- audit events.

No tenant may read, mutate, route through, or bill against another tenant's resources.

Cross-tenant isolation must be covered by automated negative tests.

## 4. Messaging Channels

The messaging core must route through a channel abstraction rather than hard-code SMS semantics into the SaaS control plane.

Initial/future channel types:

- `sms`
- `rcs`
- `whatsapp_official`
- `whatsapp_unofficial`
- `telegram`
- `email`
- future adapters

Each message records at minimum:

- `tenant_id`
- `channel_type`
- sender/connector/device selection mode
- destination
- payload/body
- message purpose (`transactional` or `campaign`)
- state
- provider/device result
- usage/billing units
- timestamps
- idempotency metadata

### 4.1 SMS

SMS continues to use the Android Remote Connector model as the first production channel.

Existing Android pairing, WebSocket connectivity, job ACK/result and duplicate-suppression behavior remain compatible during migration.

### 4.2 RCS

RCS is a planned first-class channel, not an alias for SMS.

RCS transport implementation is outside the first SaaS control-plane phase, but the data model, routing layer, entitlement system, API contracts and UI must avoid assumptions that prevent RCS later.

### 4.3 WhatsApp

Architecture must support both:

- official Meta/WhatsApp Business Platform adapters;
- isolated unofficial connector adapters.

Official and unofficial sessions/credentials must not share storage or transport code paths unnecessarily.

The UI must clearly distinguish unofficial connectors because they can have higher session-breakage, compatibility and account-blocking risk.

## 5. Device Routing

Tenants may have multiple Android devices.

Two sending modes are required:

### Manual

The user/API explicitly selects the device.

### Automatic

The platform selects an eligible device belonging to the same tenant.

Initial automatic selection strategy:

1. enabled and authorized for the requested channel;
2. online/healthy preferred;
3. within plan and rate limits;
4. lowest current queue/load or equivalent deterministic balancing metric;
5. fallback to another eligible same-tenant device when the preferred device becomes unavailable before dispatch.

The first version does not promise exactly-once physical SMS delivery. Existing idempotency and duplicate-suppression semantics remain required.

## 6. Transactional Messaging and Campaigns

Two message purposes are separate in the model:

### Transactional

- individual UI send;
- API-triggered message;
- automation/integration send.

### Campaign

Campaign capabilities:

- contact/list selection;
- CSV import;
- segmentation;
- templates;
- scheduling;
- channel selection;
- manual/automatic connector or device routing;
- rate limiting;
- durable queue;
- pause/resume;
- delivery/error reporting;
- per-campaign usage accounting.

Bulk campaign access may be restricted by plan and is disabled in the default trial profile.

## 7. Contacts and CRM Boundary

OpenSMS/RCS will maintain only the contact/list data required for communication and campaigns.

Minimum native contact model:

- contact identity;
- phone and channel identities;
- tags;
- lists;
- custom fields needed for personalization/segmentation;
- consent/opt-in metadata;
- opt-out/block state;
- communication history references.

OpenSMS/RCS will **not** duplicate a full sales CRM in the core product.

### 7.1 DeskCommCRM integration

DeskCommCRM is the preferred optional CRM integration.

It remains a separate deployment/application and is connected through an adapter/API integration.

Recommended deployment:

- OpenSMS/RCS: dedicated LXC/VM/container stack.
- DeskCommCRM: separate LXC/VM/container stack.

Do not install both products into the same application container.

Tenant mapping:

- OpenSMS `tenant_id` ↔ DeskCommCRM organization/tenant identifier.

The integration must support, as capabilities become available:

- send messages from DeskCommCRM through OpenSMS/RCS;
- select channel/device/routing mode;
- receive delivery status/webhook updates;
- associate OpenSMS message events with the relevant DeskCommCRM contact/conversation;
- optionally ingest inbound channel events into DeskCommCRM;
- preserve independent credentials and failure domains.

DeskCommCRM is an **optional tenant add-on**, not mandatory for every SaaS customer.

## 8. API Access

Both PF and PJ tenants may use the external API when their plan/trial entitles it.

Requirements:

- tenant-scoped API keys;
- key labels and creation timestamps;
- last-used metadata;
- revocation;
- scoped permissions when introduced;
- rate limits by tenant/key/plan;
- no raw key recovery after initial creation;
- audit events for key creation/revocation.

The trial permits API access with reduced limits.

Existing gateway API routes remain available during the migration period but should evolve behind compatibility adapters rather than becoming the final tenant-facing SaaS contract unchanged.

## 9. Trial

Default trial profile:

- 7 days;
- 1 device;
- 200 messages;
- up to 2 users;
- 1 API key;
- external API enabled;
- reduced rate limits;
- panel and history enabled;
- bulk campaigns disabled by default;
- no automatic charge before the user explicitly establishes a billable payment arrangement.

Trial abuse controls:

- one normal trial per CPF or CNPJ;
- verified email;
- signup rate limiting;
- detection/review of suspicious repeated registrations;
- Super Admin override for extension or courtesy trial.

Trial expiry behavior:

- new sends are blocked until plan activation;
- tenant data, devices and history are preserved;
- login remains available for conversion and billing actions unless the account is separately suspended.

Suggested notifications:

- 3 days remaining;
- 1 day remaining;
- trial expired.

## 10. Plans, Limits and Entitlements

PF and PJ have separate plan catalogs.

The billing model is hybrid:

- included device count;
- included monthly message quota;
- optional user/API/channel entitlements;
- overage policy;
- additional usage pricing where applicable.

Each plan can choose its overage policy:

- hard block at quota; or
- continue and bill overage.

Optional safety caps may limit overage exposure.

Usage alerts should support at least:

- 70%;
- 90%;
- 100%.

Entitlements must be evaluated centrally rather than scattered through UI conditionals.

## 11. Billing Architecture

Billing must use a provider-independent service layer.

Planned adapters:

- Stripe;
- Mercado Pago;
- Cora.

Conceptual boundary:

```text
BillingService
├── StripeAdapter
├── MercadoPagoAdapter
└── CoraAdapter
```

The SaaS core owns canonical subscription/entitlement state. External provider IDs and webhook events are provider-specific metadata mapped into that state.

Billing requirements:

- idempotent webhook processing;
- provider event audit trail;
- invoice/payment status mapping;
- retry-safe state transitions;
- no provider secret exposed to tenant clients;
- support manual Super Admin overrides without corrupting provider synchronization;
- future support for provider selection by country, plan or tenant.

Automatic billing implementation is a later phase after tenant isolation, entitlements and usage accounting are stable.

## 12. Signup and Tenant Provisioning

Self-service signup is required.

Flow:

1. user creates an account;
2. verifies email;
3. selects PF or PJ;
4. provides CPF or CNPJ and identity/company data;
5. selects trial or eligible plan;
6. tenant is provisioned;
7. first user becomes `Owner`;
8. tenant dashboard is available;
9. user can invite members, create API key(s) and pair devices subject to entitlements.

Paid activation later adds provider-specific checkout/payment steps without changing the tenant provisioning boundary.

## 13. Web Application Information Architecture

### Tenant application

- Dashboard
- Messages
  - Send
  - History
- Devices
- Pairing
- Campaigns
- Contacts/Lists
- API Keys
- Users & Roles
- Channels
- Integrations
  - DeskCommCRM
  - future connectors
- Usage
- Plan & Billing
- Settings

### Super Admin application

- Platform Dashboard
- Tenants
- PF Plans
- PJ Plans
- Trials
- Usage
- Billing
- Channels/Providers
- Integrations
- System Health
- Audit

The visual direction may retain the previously approved TeleGroupBot-inspired administrative concept: clear sidebar navigation, operational cards, concise tables, explicit status text and responsive behavior, without copying TeleGroupBot branding/assets/content.

## 14. Authentication and Security

Minimum requirements:

- secure password hashing;
- verified email flow;
- server-side authorization checks;
- secure session or token lifecycle;
- HttpOnly/Secure/SameSite cookies for browser sessions;
- CSRF protection for cookie-authenticated state changes;
- login and sensitive-action rate limiting;
- API key hashing or equivalent non-recoverable storage where possible;
- encrypted storage for provider/channel secrets requiring recovery;
- secret redaction in logs;
- audit trail for privileged operations;
- tenant isolation tests;
- no API/admin/device credentials embedded into client-side source;
- least-privilege access for workers and connectors.

MFA/SSO can be added as a later security phase unless required before public launch.

## 15. Persistence and Data Architecture

The current SQLite database is suitable for the existing single-gateway prototype but is not the target datastore for the multi-tenant SaaS control plane.

Target SaaS persistence: PostgreSQL.

Reasons:

- concurrent multi-user workloads;
- tenant-scoped relational integrity;
- billing and usage records;
- durable campaign queues/state;
- migrations and indexing;
- operational scaling and backups;
- stronger production tooling.

Migration strategy:

1. preserve current SQLite-backed gateway while SaaS control-plane schema is introduced;
2. add compatibility/migration layer for existing devices/messages;
3. move canonical SaaS tenant/device/message state to PostgreSQL in a controlled phase;
4. do not delete existing SQLite data until migration verification and rollback gates pass.

No production data migration should be implicit or destructive.

## 16. Service Architecture

Recommended initial logical components:

- Web/API application
- Auth/RBAC service layer
- Tenant/Entitlement service layer
- Messaging service
- Channel adapter layer
- Device connection registry/gateway
- Campaign scheduler/worker
- Usage metering service
- Billing service/adapters
- Webhook delivery/ingestion service
- Integration adapters (DeskCommCRM first)
- PostgreSQL

These may begin in a modular monolith plus workers rather than many network microservices. The code boundaries should be explicit so scaling can split services later without rewriting domain rules.

Avoid premature microservices.

## 17. Compatibility with Remote Connector v1

Must preserve during SaaS migration:

- `GET /healthz`
- `GET /readyz`
- existing Android pairing behavior until replaced by a compatible tenant-aware flow;
- device WebSocket connection behavior;
- message ACK/result handling;
- durable queue semantics;
- idempotency;
- device revocation;
- existing installed gateway data until migrated safely;
- one-command install/update philosophy;
- `rcs` management command.

Existing routes may gain compatibility wrappers but must not silently change semantics for already installed clients.

## 18. Deployment Model

The current local OpenSMS/RCS environment remains valid as the development/initial deployment base.

Current local gateway:

- IP: `192.168.170.151`
- current port: `8080`

For public SaaS production:

- use HTTPS/WSS on 443 through a reverse proxy/tunnel/load balancer;
- do not expose raw internal management services publicly;
- separate database/backups from ephemeral application containers;
- separate DeskCommCRM deployment from OpenSMS/RCS;
- environment secrets must be externalized from source control;
- backups and restore procedures are mandatory before public launch.

The one-command installer should continue to be supported for self-hosted/single-node deployments, while the SaaS production deployment may use a more robust compose/orchestrated profile.

## 19. Observability and Audit

Required platform visibility:

- gateway health;
- device online/offline counts;
- queue depth;
- message outcomes by state/channel;
- campaign progress;
- per-tenant usage;
- billing webhook failures;
- connector failures;
- integration/webhook retries;
- worker health;
- database readiness;
- audit events.

Logs must avoid message bodies and secrets by default unless an explicit, access-controlled diagnostic mode is used.

## 20. Implementation Phases

This specification defines the target architecture. Implementation should be incremental.

### Phase 0 — Preserve and harden current gateway

- keep Remote Connector v1 green;
- preserve installer and `rcs` command;
- keep existing API/Android compatibility;
- address known connector concurrency/reconnect concerns separately where confirmed by tests.

### Phase 1 — SaaS foundation

- PostgreSQL schema/migrations;
- tenants PF/PJ;
- users/memberships;
- Owner/Admin/Operator RBAC;
- tenant-scoped auth;
- Super Admin;
- plan/entitlement model;
- trial model;
- tenant-aware devices and API keys;
- tenant isolation tests.

### Phase 2 — Tenant messaging control plane

- tenant-aware SMS send/history;
- manual and automatic device routing;
- usage metering;
- quotas and overage policy enforcement;
- tenant dashboard;
- compatibility bridge to Remote Connector v1.

### Phase 3 — Campaigns

- contacts/lists;
- CSV import;
- campaigns/templates/scheduling;
- queue/worker controls;
- campaign usage and reporting.

### Phase 4 — Billing

- provider-independent billing core;
- Stripe adapter;
- Mercado Pago adapter;
- Cora adapter;
- provider webhooks;
- paid subscription activation;
- overage billing.

### Phase 5 — DeskCommCRM connector

- optional tenant add-on;
- tenant/org mapping;
- outbound send integration;
- delivery callbacks;
- contact/conversation event bridge where supported.

### Phase 6 — Additional channels

- RCS transport;
- WhatsApp official;
- WhatsApp unofficial isolated adapter;
- other channels.

## 21. Testing Strategy

Implementation must follow TDD for domain behavior and regression protection.

Minimum coverage categories:

1. tenant isolation (read/write negative tests);
2. RBAC matrix for Owner/Admin/Operator/Super Admin;
3. PF/PJ plan eligibility;
4. trial limits and expiry;
5. API key tenant scoping and revocation;
6. device ownership and pairing;
7. manual routing;
8. automatic routing and same-tenant fallback;
9. quota and overage policies;
10. usage metering idempotency;
11. campaign scheduling and pause/resume;
12. billing webhook idempotency;
13. connector/integration retries;
14. existing gateway API regression tests;
15. Android Remote Connector regression tests;
16. installer/update regression tests;
17. security tests for secret leakage and cross-tenant access;
18. migration tests from existing SQLite state to the new control plane.

## 22. Acceptance Criteria for SaaS Foundation

The first SaaS milestone is accepted when:

- PF and PJ tenants can be created;
- CPF/CNPJ identity is stored in the correct tenant type;
- first user is Owner;
- tenant can invite users with Admin/Operator roles;
- tenant isolation tests pass;
- Super Admin can manage tenants and plans;
- trial can be provisioned with configured limits;
- API access works in trial under reduced limits;
- tenant can pair at least one Android device;
- tenant can send SMS using an owned device;
- another tenant cannot see or use that device/message/API key;
- manual and automatic routing are represented in the domain model;
- usage is metered against the tenant;
- current Android connector and gateway remain operational through the compatibility layer;
- no existing production data is destroyed;
- CI is green.

## 23. Deferred Decisions / Later Gates

Separate design gates are required before public launch or implementation of these areas if requirements materially expand:

- exact PF/PJ plan names and prices;
- overage unit prices;
- tax/fiscal document workflows;
- exact Stripe/Mercado Pago/Cora payment-method matrix;
- MFA/SSO policy;
- RCS provider/transport implementation;
- WhatsApp unofficial connector technology choice;
- public API versioning details beyond the compatibility phase;
- high-availability topology;
- data retention periods and customer-configurable retention;
- formal LGPD operational policy and DPA/legal documents.

## 24. Core Product Boundary

OpenSMS/RCS is the communications SaaS and messaging control plane.

It owns:

- tenants;
- users/RBAC;
- devices/connectors;
- channels;
- messages;
- campaigns;
- API keys;
- usage;
- plans/trials;
- billing integration;
- messaging-related contacts/lists;
- integrations.

DeskCommCRM remains the optional full CRM and sales/attendance platform.

This boundary must be preserved to avoid turning OpenSMS/RCS into an unmaintainable CRM + messaging monolith.