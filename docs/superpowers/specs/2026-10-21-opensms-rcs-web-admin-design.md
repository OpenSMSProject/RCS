# OpenSMS/RCS Web Admin Panel — Design Specification

Date: 2026-10-21
Branch: `feature/remote-connector-v1`
Status: Proposed for implementation after user review

## 1. Goal

Add a lightweight administrative web panel to the existing OpenSMS/RCS Gateway so that opening the gateway root URL provides a usable control surface instead of `{"detail":"Not Found"}`.

The panel should follow the operational concept of the user's TeleGroupBot interface: clean administrative layout, persistent navigation, high-signal status cards, direct operational actions, and clear status text. It must not copy TeleGroupBot branding, proprietary content, or assets.

Primary local target:

- `http://192.168.170.151:8080/`

The gateway API and Android connector remain the source of truth. The web panel is an administrative layer on top of the existing backend.

## 2. Non-goals

This phase does not:

- change Android package identifiers;
- implement RCS message transport;
- replace the existing SMS gateway API;
- expose raw API/admin tokens to the browser UI;
- introduce Node.js, React, a second application server, or a second container;
- merge the feature branch into `main` automatically;
- remove or change existing `/api/v1/...`, `/healthz`, `/readyz`, or WebSocket contracts.

## 3. Architecture

The panel will be served by the existing FastAPI gateway in the same Docker container.

Recommended structure:

- FastAPI remains the application server.
- Server-rendered HTML templates for the admin pages.
- Static CSS and minimal JavaScript bundled with the Python application.
- Existing SQLite gateway database remains the persistent source for devices and messages.
- Administrative web actions call backend service functions or dedicated web routes on the server side rather than exposing the raw admin token to client-side JavaScript.

This keeps deployment simple:

- one LXC;
- one repository;
- one Docker Compose project;
- one gateway container;
- one persistent SQLite volume;
- one `rcs update` workflow.

## 4. Security Model

The administrative UI must be protected independently from the device WebSocket and public pairing endpoint.

Requirements:

1. `/` must not expose administrative data without authentication.
2. Admin authentication must use a server-side session.
3. The existing `OPENSMS_ADMIN_TOKEN` and `OPENSMS_API_TOKEN` remain backend secrets and must never be embedded in HTML, JavaScript, logs, or browser-local storage.
4. Session cookies must be `HttpOnly`, `SameSite=Strict` or equivalent safe configuration, and `Secure` when HTTPS is in use.
5. State-changing form actions must use CSRF protection or an equivalent same-origin mechanism.
6. Login failures must not disclose whether a particular credential value is partly correct.
7. Device credentials remain hidden.
8. Message text may be displayed in the authenticated message history, but must not be emitted into application logs by default.

For the first local deployment, the installer may derive or provision a separate web-admin credential securely and store only the necessary server-side secret in the `.env`. It must not print that credential into CI logs or normal service logs.

## 5. Navigation and Information Architecture

The admin UI will use a persistent left sidebar on desktop and a compact navigation pattern on narrow screens.

Sections:

### 5.1 Dashboard

Purpose: immediate operational overview.

Show:

- Gateway status: Online / Degraded / Offline.
- Docker/service status where available to the application.
- Health check status.
- Ready check status.
- Number of registered devices.
- Number of online devices.
- Message counts by meaningful state.
- Recent message activity.
- Current branch.
- Current commit.
- Gateway IP/port or configured public URL.

Status must be textual as well as visual. Example:

- `Operational — no action required`
- `Device offline — messages will remain queued`
- `Storage unavailable — check SQLite volume`

### 5.2 Devices

Show a table or responsive list with:

- device name;
- device ID;
- enabled/revoked state;
- online/offline state;
- last contact / heartbeat;
- created/paired timestamp where available;
- action to revoke a device.

Revocation must require explicit confirmation.

### 5.3 Pairing

Purpose: create and present a pairing code for an Android device.

Flow:

1. Authenticated administrator opens Pairing.
2. Clicks `Generate pairing code`.
3. Backend creates a six-digit code using the existing pairing mechanism.
4. UI displays:
   - code;
   - expiration time;
   - countdown or clear expiry text;
   - concise instructions for entering the code in the Android app.
5. Expired codes are visibly marked expired and must not appear valid.

### 5.4 Send SMS

Form fields:

- device selector;
- destination number;
- message text;
- submit button.

Behavior:

- only enabled devices are selectable;
- online/offline status is shown next to each device;
- offline devices may still accept a queued message if supported by the existing gateway semantics;
- successful submission shows the message ID and initial state;
- validation failures are displayed in human-readable form;
- duplicate submissions should use the gateway's idempotency mechanism where practical.

### 5.5 Messages / History

Display recent and searchable message records.

Minimum fields:

- message ID;
- device;
- destination;
- message preview;
- state;
- created time;
- updated/completed time;
- error code when present;
- dispatch attempts.

States should be rendered with clear labels:

- queued;
- waiting_device;
- dispatching;
- acknowledged;
- sent;
- failed.

Filtering should support at least state and device. Pagination should be used rather than loading unbounded history.

### 5.6 System

Show operational metadata:

- app version;
- branch;
- commit;
- health status;
- ready status;
- database readiness;
- local bind/port;
- configured public URL if present;
- container/runtime metadata that is safely available.

No secrets are shown.

### 5.7 Settings

First version should be deliberately small.

Possible settings:

- display/public base URL;
- UI preferences that are safe to expose;
- administrative password rotation workflow.

Raw gateway tokens are not editable through the browser in v1.

## 6. Required Backend Additions

The existing API does not currently provide every dashboard/history view needed by the UI. Add only the minimum server-side capabilities necessary.

Likely additions:

- root/login/logout web routes;
- server-side authenticated session support;
- template/static serving;
- dashboard aggregation helper;
- paginated message listing for authenticated admin use;
- message counts by state;
- device detail metadata needed by the table;
- application build/version metadata endpoint or helper;
- safe web-admin actions for pairing, revocation, and message submission.

These additions must not weaken authentication on the existing API routes.

## 7. UI Design Direction

Visual language:

- dark or neutral sidebar;
- light primary content area;
- cards with strong hierarchy;
- compact tables;
- rounded but restrained controls;
- clear success/warning/error badges;
- responsive layout;
- no decorative complexity that makes operational status harder to scan.

Brand:

- `OpenSMS/RCS` in the header/sidebar;
- SMS/message-oriented iconography;
- no TeleGroupBot logo, name, assets, or copied text.

The visual reference should influence organization and usability, not produce a pixel-identical clone.

## 8. Installer and Operations Integration

The existing one-command install/update flow must remain intact.

After implementation:

- `install.sh` includes all Python/template/static dependencies required by the panel through the existing Docker build;
- `rcs update` pulls the web panel along with the gateway and rebuilds the same container;
- `.env` and SQLite data remain preserved;
- `rcs status` reports the gateway and web admin as part of the same application status;
- installation output continues to show `LOCAL_ACCESS=http://<LAN_IP>:8080`;
- after installation, opening `LOCAL_ACCESS` must produce the admin login/page rather than FastAPI 404.

## 9. Compatibility Constraints

Must preserve:

- `GET /healthz`;
- `GET /readyz`;
- `POST /api/v1/pairing-codes`;
- `POST /api/v1/devices/pair`;
- `GET /api/v1/devices`;
- `DELETE /api/v1/devices/{device_id}`;
- `POST /api/v1/messages`;
- `GET /api/v1/messages/{message_id}`;
- `WS /api/v1/device/connect`;
- current Android pairing and remote connector behavior;
- SQLite persistence and existing device/message records;
- current Docker Compose deployment model.

## 10. Testing Strategy

Implementation should follow TDD.

Minimum automated coverage:

1. unauthenticated `/` redirects to login or returns the intended login page;
2. authenticated dashboard renders safely;
3. admin token/API token values never appear in rendered HTML;
4. pairing code generation works through the UI;
5. device list renders online/offline status;
6. device revocation requires authenticated state-changing request;
7. SMS submission from the UI creates a gateway message;
8. message history pagination/filtering works;
9. existing gateway API tests continue to pass;
10. health and readiness routes remain unchanged;
11. installer contract tests ensure the panel is available at `LOCAL_ACCESS` after health validation;
12. static/template assets are present in the Docker image;
13. CI remains green.

A manual browser acceptance pass should verify desktop and mobile-width layouts.

## 11. Acceptance Criteria

The feature is considered complete when:

- `http://192.168.170.151:8080/` opens the OpenSMS/RCS admin login/panel, not a 404;
- an authenticated administrator can see gateway status;
- paired devices and their online/offline state are visible;
- a pairing code can be generated;
- an SMS can be submitted through the panel;
- message delivery state can be followed in history;
- device revocation works;
- no backend tokens or device credentials are exposed in the browser;
- the Android connector and existing API continue to pass their tests;
- `rcs update` installs/updates the panel automatically;
- the feature remains on `feature/remote-connector-v1` until separately approved for merge.

## 12. Future Extensions

Explicitly deferred:

- RCS-specific messaging UI;
- MMS/media attachments;
- bulk campaigns;
- contact/address book management;
- multi-user RBAC;
- analytics dashboards beyond basic operational counters;
- internet-facing SSO;
- tenant/multi-organization support.

These should be separate design gates after the SMS web administration flow is stable.