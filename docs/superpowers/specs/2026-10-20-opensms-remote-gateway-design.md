# OpenSMS Remote Gateway v1 — Design Specification

Date: 2026-10-20
Branch: `feature/remote-connector-v1`
Status: design review

## 1. Objective

Allow an Android phone running OpenSMS to send SMS commands received from anywhere on the Internet without requiring the caller and phone to be on the same LAN, without exposing TCP/9292 on the phone, and without requiring a public IP on the phone.

The Android device must initiate and maintain the outbound connection to a central gateway over `wss://` on TCP/443. The current local `/sms/` FastAPI endpoint remains available as an optional local-mode fallback.

Success for v1 means a client can submit one API request to the gateway, the selected Android device can receive the job over its outbound connection, execute the existing Android `SmsManager` path, and report a durable final state back to the gateway.

## 2. Scope

### Included

- outbound-only Android connector
- remote device enrollment/pairing
- unique device identity and credential
- persistent WebSocket session
- heartbeat and online/offline status
- remote `send_sms` jobs
- ACK and final job result
- persistent gateway queue
- reconnect and redelivery of unfinished jobs
- idempotency to reduce duplicate SMS sends
- REST API for message submission and status
- minimal Android settings/pairing UI
- local `/sms/` API retained
- tests for protocol, queue, auth, reconnect, and SMS dispatch adapter
- deployment documentation for an HTTPS/WSS gateway

### Explicitly excluded from v1

- RCS transport
- MMS
- campaign/bulk marketing engine
- billing
- multi-tenant SaaS administration
- VPN/IP-overlay networking
- remote shell or general-purpose device tunneling

The connector transports only OpenSMS protocol messages; it is not a replacement for Tailscale as a general VPN.

## 3. High-level architecture

```text
External client
      |
      | HTTPS / TCP 443
      v
+-----------------------------+
| OpenSMS Gateway             |
|                             |
| REST API                    |
| Device registry             |
| Pairing service             |
| Persistent queue            |
| WebSocket device endpoint   |
+--------------+--------------+
               |
               | WSS / TCP 443
               | outbound connection initiated by phone
               v
+-----------------------------+
| OpenSMS Android             |
| background service          |
| remote connector            |
| job executor                |
| SmsManager adapter          |
+--------------+--------------+
               |
               v
             SIM/SMS
```

## 4. Android responsibilities

The Android background service owns the connector lifecycle. The UI is not responsible for keeping the remote session alive.

Responsibilities:

1. load connector configuration
2. establish `wss://` connection
3. authenticate the device
4. send heartbeat
5. receive supported jobs
6. validate payloads
7. acknowledge accepted jobs
8. execute `send_sms` through the existing `services.smsApi.send_sms()` implementation
9. report final result
10. reconnect with exponential backoff and jitter
11. retain enough local job state to reject an immediately repeated completed `job_id`

The connector must not expose a remote shell, arbitrary URL fetcher, file write command, or generic command execution mechanism.

## 5. Gateway responsibilities

The gateway is a separate server-side component and must not run inside the Android process.

Responsibilities:

- provide pairing endpoints
- issue device credentials
- authenticate WebSocket devices
- maintain device connection registry
- store device metadata and last-seen timestamps
- accept message requests via REST
- persist message jobs before attempting delivery
- dispatch jobs only to the selected/eligible device
- update state when ACK/result frames arrive
- retry jobs that were queued but not definitively completed
- expose message status endpoint
- provide health/readiness endpoints

For v1, SQLite is acceptable for a single-node gateway. Storage interfaces should remain narrow so PostgreSQL can replace SQLite later without changing the protocol.

## 6. Device identity and pairing

### Pairing flow

1. An administrator creates a short-lived pairing code on the gateway.
2. The user enters the gateway URL and pairing code in the OpenSMS Android app.
3. Android generates a random `device_id` if one does not already exist.
4. Android calls the gateway pairing endpoint over HTTPS.
5. Gateway validates the one-time code and issues a device credential.
6. Android stores the credential in app-private storage.
7. Pairing code is invalidated after successful use or expiry.
8. Subsequent WebSocket sessions use the device credential, not the pairing code.

### Credential rules

- per-device credential
- high entropy
- stored hashed on the gateway where feasible
- never logged
- revocable per device
- pairing code expires quickly and is single use
- no global credential shared by all phones

## 7. Gateway REST API

All routes are versioned under `/api/v1`.

### `POST /api/v1/pairing-codes`

Administrative operation. Creates a short-lived one-time pairing code.

### `POST /api/v1/devices/pair`

Example request:

```json
{
  "pairing_code": "824921",
  "device_id": "osms-7a8f1e",
  "name": "Galaxy A32 Escritorio"
}
```

Successful response returns a device credential exactly once.

### `GET /api/v1/devices`

Returns registered devices and status metadata, including online/offline and last seen.

### `POST /api/v1/messages`

Example request:

```json
{
  "device_id": "osms-7a8f1e",
  "to": "+5561999999999",
  "text": "Teste OpenSMS",
  "idempotency_key": "optional-client-key"
}
```

Response:

```json
{
  "message_id": "msg_...",
  "state": "queued"
}
```

### `GET /api/v1/messages/{message_id}`

Returns current state, timestamps, selected device, and safe error code when relevant.

### `GET /healthz`

Process liveness.

### `GET /readyz`

Storage and service readiness.

## 8. WebSocket protocol

Endpoint:

`wss://<gateway>/api/v1/device/connect`

Protocol version: `1`.

### Android -> Gateway: `hello`

```json
{
  "type": "hello",
  "protocol": 1,
  "device_id": "osms-7a8f1e",
  "credential": "<secret>",
  "agent": "opensms-android",
  "app_version": "0.1.0"
}
```

Authentication must complete before the gateway dispatches jobs.

### Android -> Gateway: `heartbeat`

```json
{
  "type": "heartbeat",
  "device_id": "osms-7a8f1e",
  "timestamp": 1792530000
}
```

Optional capability metadata can be added later without changing the core protocol.

### Gateway -> Android: `job`

```json
{
  "type": "job",
  "job_id": "job_...",
  "command": "send_sms",
  "number": "+5561999999999",
  "text": "Teste OpenSMS"
}
```

### Android -> Gateway: `job_ack`

Sent after validation and acceptance, before SMS execution.

```json
{
  "type": "job_ack",
  "job_id": "job_...",
  "device_id": "osms-7a8f1e"
}
```

### Android -> Gateway: `job_result`

```json
{
  "type": "job_result",
  "job_id": "job_...",
  "device_id": "osms-7a8f1e",
  "ok": true,
  "error": null
}
```

Allowed stable error examples:

- `invalid_payload`
- `unsupported_command`
- `sms_send_failed`
- `permission_denied`
- `device_not_ready`

Python exception strings must not be exposed to API clients.

### Ping/pong

The gateway may send protocol `ping`; Android replies with `pong`. WebSocket transport ping/pong may also be enabled by the server.

## 9. Message state machine

```text
queued
  |
  +--> waiting_device
  |
  +--> dispatching
          |
          +--> acknowledged
                    |
                    +--> sent
                    |
                    +--> failed
```

Terminal states:

- `sent`
- `failed`

The gateway persists a job before dispatch.

A disconnect before ACK leaves the job eligible for redelivery.

A disconnect after ACK but before final result is ambiguous. To reduce duplicate SMS sends, Android keeps a bounded cache of recently completed `job_id` values and returns the prior result when the same job is redelivered.

This is at-least-once transport with application-level idempotency; the design must not claim mathematically exact once-only SMS delivery because Android/carrier APIs cannot provide that guarantee end-to-end.

## 10. Queue/storage model

Minimum gateway tables:

### `devices`

- `device_id` primary key
- `name`
- `credential_hash`
- `enabled`
- `created_at`
- `last_seen_at`
- `last_ip` optional/audit-only

### `pairing_codes`

- `code_hash`
- `expires_at`
- `used_at`
- `created_at`

### `messages`

- `message_id` primary key
- `device_id`
- `to_number`
- `text`
- `state`
- `idempotency_key` nullable unique within caller scope
- `created_at`
- `updated_at`
- `acknowledged_at`
- `completed_at`
- `error_code` nullable
- `dispatch_attempts`

Sensitive credentials are never stored in plaintext logs.

## 11. Android UI

Add a Remote Connector section to Settings.

Fields/status:

- gateway URL
- pairing code input only while unpaired
- device display name
- connect/pair action
- connector enabled toggle
- status: `Disconnected`, `Connecting`, `Online`, `Authentication failed`
- device ID read-only after enrollment
- unpair/revoke-local-credential action

The app must explain that the phone can use Wi-Fi or mobile data and does not need to be on the same network as the API client.

## 12. Local API compatibility

Existing behavior remains valid:

`POST /sms/` -> existing `send_sms()` path.

Remote mode does not require the local FastAPI server to be reachable from the Internet. The local server may continue to be started/stopped independently for LAN use.

## 13. Security requirements

- production gateway requires TLS; `wss://`/`https://`
- reject plaintext `ws://` for non-development gateway configurations
- authenticate every device session
- validate `device_id` against authenticated credential
- rate-limit pairing attempts
- rate-limit public message API by caller credential
- maximum text/payload lengths
- normalize/validate destination phone number before dispatch
- do not log message credentials or full authorization headers
- do not log device credentials
- do not implement arbitrary remote execution
- gateway administrative credentials are distinct from device credentials
- revoked/disabled devices cannot reconnect

## 14. Reliability requirements

- reconnect uses exponential backoff plus jitter
- heartbeat interval configurable with safe lower bound
- gateway marks stale sessions offline after heartbeat timeout
- jobs are durable before dispatch
- reconnect wakes queued jobs for that device
- server restart must not lose queued jobs
- Android connector restart must not erase device identity/credential
- bounded recent-job result cache on Android reduces duplicate sends

## 15. Observability

Gateway logs must include safe identifiers:

- message ID
- job ID
- device ID
- state transition
- attempt number

Do not log device secrets.

Metrics useful for later versions:

- connected devices
- queued messages
- send success/failure counts
- reconnect count
- message latency

## 16. Testing strategy

### Unit tests

- connector config load/defaults
- protocol frame validation
- authentication success/failure
- pairing code expiry/single-use
- message state transitions
- idempotency behavior
- dispatcher behavior for offline devices
- duplicate job handling

### Integration tests

- fake WebSocket device connects and authenticates
- queued message dispatched after device connects
- ACK updates state
- result updates terminal state
- reconnect redelivers unacknowledged job
- completed duplicate `job_id` does not trigger second adapter invocation

### Android/build gate

- Buildozer Android build succeeds
- app starts with connector disabled
- local `/sms/` behavior remains unchanged
- connector can stay online with screen not on the connector settings page
- SMS permission denial produces a controlled failure

### Network acceptance test

Required before declaring v1 complete:

1. gateway hosted outside the phone LAN
2. Android connected through Wi-Fi sends SMS successfully
3. Android changes to mobile data/4G/5G
4. connector automatically reconnects
5. second remote SMS succeeds without changing gateway configuration
6. phone has no inbound port forwarded

## 17. Deployment model

Recommended v1 deployment:

- one Linux server/VPS
- gateway process behind a reverse proxy supporting WebSocket upgrade
- HTTPS/WSS on TCP/443
- SQLite database on persistent disk
- systemd service for gateway

A custom DNS name such as `sms.example.com` may point to the gateway. The design does not require exposing the Android device or using a VPN overlay.

## 18. Migration/implementation order

1. freeze protocol models and validators
2. implement gateway storage and state machine
3. implement pairing/authentication
4. implement WebSocket registry and dispatcher
5. implement Android job execution + ACK/result
6. implement duplicate-job cache
7. implement Android pairing/settings UI
8. add automated tests
9. build APK
10. deploy test gateway
11. execute Wi-Fi -> mobile-data acceptance test
12. only then mark PR ready for merge

## 19. Definition of Done

Remote Gateway v1 is complete only when all of the following are true:

- Android can pair with a remote gateway
- device reconnects automatically across network changes
- client can submit an SMS through gateway REST API
- message is durably queued before dispatch
- Android receives and validates the job
- existing `SmsManager` path executes the SMS
- gateway receives ACK and final result
- message status endpoint exposes the final state
- reconnect does not silently lose queued work
- automated tests pass
- Android APK builds
- manual Wi-Fi and mobile-data acceptance tests pass
- documentation covers server deployment and phone pairing
- PR has no secrets or test credentials committed
