# OpenSMS Remote Gateway v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a production-ready v1 where an OpenSMS Android device can pair with a central Internet gateway, stay connected outbound over WSS/443, receive durable `send_sms` jobs, execute the existing Android `SmsManager` path, and report durable final state without requiring the phone and caller to share a LAN.

**Architecture:** Keep the Android app as the SMS execution edge and add a separate FastAPI gateway with SQLite persistence. The phone owns an outbound-only WebSocket session; the gateway owns authentication, device registry, pairing, queue/state transitions and REST submission. Delivery is at-least-once at the gateway with phone-side duplicate suppression keyed by `job_id` to reduce duplicate SMS after reconnects.

**Tech Stack:** Python 3.11+, FastAPI, Uvicorn, SQLite (`sqlite3`), `websocket-client`, Kivy/KivyMD, Pyjnius/Android `SmsManager`, pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-20-opensms-remote-gateway-design.md`

## Global Constraints

- Remote Android operation must require no inbound phone port, no public phone IP, and no shared LAN.
- Device transport is outbound `wss://` over TCP/443 in production.
- Existing local `/sms/` FastAPI operation remains available and compatible.
- Remote protocol version is exactly `1` for v1.
- Each Android device has its own revocable high-entropy credential; no credential is shared across devices.
- Pairing codes are single-use and short-lived.
- Device credentials, API tokens and pairing secrets must never be logged.
- Gateway persists a job before attempting delivery.
- Android connector exposes only the OpenSMS protocol; no shell, arbitrary file operation, URL fetcher or generic command execution.
- RCS, MMS, bulk campaign features, billing, multi-tenant SaaS and VPN overlay networking remain out of scope.
- `SmsManager` remains the only Android SMS transport used by v1.

## Review Focus

- Duplicate delivery after disconnect between SMS transmission and gateway result: Android must suppress a repeated `job_id` whose prior execution is complete or ambiguous rather than blindly send it twice.
- Expired/used pairing code: pairing must fail without issuing a device credential and without leaking which credential already exists.
- Revoked or invalid device credential: WebSocket authentication must fail before any queued job is disclosed or dispatched.
- Gateway restart with queued/acknowledged jobs: durable state must survive SQLite reopen and eligible unfinished jobs must be rediscovered safely.
- Malformed/oversized message input: REST and device protocol validation must reject empty number/text and enforce explicit v1 size limits without crashing the service.

---

### Task 1: Harden connector configuration and phone-side job ledger

**Files:**
- Modify: `app/services/connectorConfig.py`
- Create: `app/services/jobLedger.py`
- Create: `tests/app/test_connector_config.py`
- Create: `tests/app/test_job_ledger.py`
- Create: `requirements-dev.txt`

**Interfaces:**
- Produces: `load_connector_config(config_dir: str) -> dict`
- Produces: `save_connector_config(config_dir: str, config: dict) -> None`
- Produces: `ensure_device_id(config: dict) -> dict`
- Produces: `JobLedger(path: str)` with `get(job_id: str) -> dict | None`, `mark(job_id: str, state: str, result: dict | None = None) -> None`, and `prune(max_entries: int = 500) -> None`
- Consumes: app-private `config_dir` already established by `app/services/appSvc.py`

- [ ] **Step 1: Write failing connector configuration tests**

Cover defaults, persistence of `enabled`, HTTPS gateway base URL, generated `device_id`, per-device `device_credential`, minimum heartbeat of 10 seconds, malformed JSON fallback, and no credential value in exception/log formatting.

- [ ] **Step 2: Run connector configuration tests and verify failure**

Run: `python -m pytest tests/app/test_connector_config.py -v`
Expected: FAIL because the new schema/device identity behavior is not implemented.

- [ ] **Step 3: Implement connector configuration schema**

In `app/services/connectorConfig.py`, keep JSON storage in app-private storage and define exact keys: `enabled`, `gateway_url`, `device_id`, `device_name`, `device_credential`, `heartbeat_seconds`. `ensure_device_id()` must create `osms-<12 lowercase hex chars>` once and preserve it thereafter.

- [ ] **Step 4: Write failing phone-side ledger tests**

Assert a new ledger returns no record, `mark()` survives re-open, completed jobs preserve prior result, an `accepted`/`sending` record can be recognized as ambiguous after restart, and `prune(500)` never retains more than 500 newest entries.

- [ ] **Step 5: Run ledger tests and verify failure**

Run: `python -m pytest tests/app/test_job_ledger.py -v`
Expected: FAIL because `JobLedger` does not exist.

- [ ] **Step 6: Implement `JobLedger`**

Use a small JSON file next to connector config with atomic replace (`.tmp` then `os.replace`). States used by the Android side: `accepted`, `sending`, `sent`, `failed`, `ambiguous`.

- [ ] **Step 7: Run Task 1 tests**

Run: `python -m pytest tests/app/test_connector_config.py tests/app/test_job_ledger.py -v`
Expected: PASS.

- [ ] **Step 8: Commit Task 1**

```bash
git add app/services/connectorConfig.py app/services/jobLedger.py tests/app/test_connector_config.py tests/app/test_job_ledger.py requirements-dev.txt
git commit -m "feat: harden connector identity and job ledger"
```

### Task 2: Complete Android remote job execution protocol

**Files:**
- Modify: `app/services/remoteConnector.py`
- Modify: `app/services/appSvc.py`
- Test: `tests/app/test_remote_connector.py`

**Interfaces:**
- Consumes: `JobLedger`, `load_connector_config()`, existing `services.smsApi.send_sms(phone: str, msg: str) -> bool`
- Produces: `RemoteConnector(config_dir: str, sms_sender: Callable[[str, str], bool] = send_sms)`
- Produces protocol frames `hello`, `heartbeat`, `pong`, `job_ack`, `job_result`

- [ ] **Step 1: Write failing protocol tests**

Test `hello` includes protocol `1`, device id and credential; no job is handled before authenticated connection; `ping` yields `pong`; malformed JSON does not terminate the process loop; unsupported command returns `job_result` with `unsupported_command`.

- [ ] **Step 2: Write failing `send_sms` job tests**

Assert valid jobs validate `job_id`, `number`, `text`; ACK is emitted before calling `sms_sender`; successful sender returns final `sent`; false/exception returns `failed` with safe error code; payload limits are number <= 64 chars and text 1..4000 chars.

- [ ] **Step 3: Add duplicate suppression tests**

For a prior ledger state `sent`, repeated `job_id` must return the prior terminal result without calling `sms_sender`. For `accepted`, `sending` or `ambiguous`, repeated `job_id` must not call `sms_sender` and must return `failed` with `duplicate_suppressed_uncertain`.

- [ ] **Step 4: Run remote connector tests and verify failure**

Run: `python -m pytest tests/app/test_remote_connector.py -v`
Expected: FAIL against the current heartbeat-only connector.

- [ ] **Step 5: Implement authenticated job handling**

Update `RemoteConnector` to authenticate with the configured device credential, create/use `JobLedger`, validate only `command == "send_sms"`, ACK accepted jobs, mark `sending` before calling `sms_sender`, persist terminal result before sending `job_result`, and never include secrets or message text in connector status strings.

- [ ] **Step 6: Inject the existing SMS adapter from the Android background service**

Update `app/services/appSvc.py` to pass `services.smsApi.send_sms` into `RemoteConnector` while keeping local `PosiApiServer` behavior unchanged.

- [ ] **Step 7: Run Task 2 tests plus legacy import smoke tests**

Run: `python -m pytest tests/app/test_remote_connector.py tests/app/test_connector_config.py tests/app/test_job_ledger.py -v`
Expected: PASS.

Run: `python -m py_compile app/services/remoteConnector.py app/services/appSvc.py app/services/smsApi.py`
Expected: exit 0.

- [ ] **Step 8: Commit Task 2**

```bash
git add app/services/remoteConnector.py app/services/appSvc.py tests/app/test_remote_connector.py
git commit -m "feat: execute authenticated remote sms jobs"
```

### Task 3: Build gateway security and durable SQLite storage

**Files:**
- Create: `gateway/opensms_gateway/__init__.py`
- Create: `gateway/opensms_gateway/config.py`
- Create: `gateway/opensms_gateway/security.py`
- Create: `gateway/opensms_gateway/storage.py`
- Create: `gateway/requirements.txt`
- Create: `tests/gateway/test_security.py`
- Create: `tests/gateway/test_storage.py`

**Interfaces:**
- Produces: `GatewaySettings.from_env() -> GatewaySettings`
- Produces: `hash_secret(secret: str) -> str`, `verify_secret(secret: str, encoded: str) -> bool`, `new_secret(prefix: str) -> str`
- Produces: `GatewayStore(db_path: str)` with schema initialization, pairing-code, device and message CRUD/state-transition methods
- State values: `queued`, `waiting_device`, `dispatching`, `acknowledged`, `sent`, `failed`

- [ ] **Step 1: Write failing security tests**

Assert generated secrets are high entropy and prefixed, hashes do not contain the raw secret, valid verification passes, invalid verification fails, and comparisons are timing-safe through `secrets.compare_digest`-based verification.

- [ ] **Step 2: Write failing storage schema/state tests**

Cover single-use pairing-code expiration, hashed device credential storage, revocation flag, idempotency-key uniqueness, persistence after DB reopen, valid state transitions, terminal states not returning as dispatchable, and queued/acknowledged restart recovery behavior defined by the spec.

- [ ] **Step 3: Run gateway storage/security tests and verify failure**

Run: `python -m pytest tests/gateway/test_security.py tests/gateway/test_storage.py -v`
Expected: FAIL because gateway package does not exist.

- [ ] **Step 4: Implement gateway settings and security helpers**

Environment variables: `OPENSMS_DB_PATH` default `./data/opensms-gateway.sqlite3`, required `OPENSMS_API_TOKEN`, required `OPENSMS_ADMIN_TOKEN`, `OPENSMS_PAIRING_TTL_SECONDS` default `300`.

- [ ] **Step 5: Implement SQLite schema and explicit state transitions**

Tables: `pairing_codes`, `devices`, `messages`. Use transactions around code consumption, credential issue, message creation and state changes. Store only secret hashes. `idempotency_key` is nullable but unique when present.

- [ ] **Step 6: Run Task 3 tests**

Run: `python -m pytest tests/gateway/test_security.py tests/gateway/test_storage.py -v`
Expected: PASS.

- [ ] **Step 7: Commit Task 3**

```bash
git add gateway/opensms_gateway gateway/requirements.txt tests/gateway/test_security.py tests/gateway/test_storage.py
git commit -m "feat: add gateway security and durable storage"
```

### Task 4: Implement gateway REST API, pairing and WebSocket dispatch

**Files:**
- Create: `gateway/opensms_gateway/models.py`
- Create: `gateway/opensms_gateway/registry.py`
- Create: `gateway/opensms_gateway/app.py`
- Create: `gateway/run.py`
- Create: `tests/gateway/test_api.py`
- Create: `tests/gateway/test_websocket.py`

**Interfaces:**
- Consumes: `GatewaySettings`, `GatewayStore`, security helpers
- Produces: FastAPI `app`
- Produces routes `POST /api/v1/pairing-codes`, `POST /api/v1/devices/pair`, `GET /api/v1/devices`, `POST /api/v1/messages`, `GET /api/v1/messages/{message_id}`, `GET /healthz`, `GET /readyz`, WS `/api/v1/device/connect`
- Produces: `ConnectionRegistry` with one active session per device and `enqueue(device_id: str, job: dict) -> bool`

- [ ] **Step 1: Write failing REST authentication/pairing tests**

Assert admin routes require `Authorization: Bearer <OPENSMS_ADMIN_TOKEN>`, message/status routes require `Authorization: Bearer <OPENSMS_API_TOKEN>`, pairing code is one-use/TTL-bound, device credential is returned only on successful pairing, and device list never exposes credential hashes.

- [ ] **Step 2: Write failing message validation/idempotency tests**

Validate E.164-like destination input starts with `+` and has 8..15 digits, text is 1..4000 chars, unknown/revoked device is rejected, accepted message is persisted before dispatch, repeated idempotency key returns the original `message_id`, and malformed/oversized payloads return 422.

- [ ] **Step 3: Write failing WebSocket tests**

Assert credential authentication happens before dispatch, invalid/revoked credentials close without jobs, successful `hello` marks online, disconnect marks offline, queued jobs dispatch after connection, `job_ack` moves to `acknowledged`, `job_result(sent)` moves to `sent`, failed result records only a safe error code, and reconnect rediscovers eligible pending jobs.

- [ ] **Step 4: Run API/WebSocket tests and verify failure**

Run: `python -m pytest tests/gateway/test_api.py tests/gateway/test_websocket.py -v`
Expected: FAIL because API/registry are not implemented.

- [ ] **Step 5: Implement Pydantic request/response models and REST routes**

Keep secret-bearing responses limited to the one-time pairing credential. Never serialize stored secret hashes. Health routes are unauthenticated and expose no sensitive configuration.

- [ ] **Step 6: Implement connection registry and WebSocket handler**

Authenticate the first `hello` frame, allow one live connection per device (new authenticated connection replaces stale one), update `last_seen`, dispatch persisted jobs, and process only `heartbeat`, `pong`, `job_ack`, and `job_result` from the device.

- [ ] **Step 7: Run Task 4 tests**

Run: `python -m pytest tests/gateway/test_api.py tests/gateway/test_websocket.py tests/gateway/test_storage.py tests/gateway/test_security.py -v`
Expected: PASS.

- [ ] **Step 8: Commit Task 4**

```bash
git add gateway/opensms_gateway/models.py gateway/opensms_gateway/registry.py gateway/opensms_gateway/app.py gateway/run.py tests/gateway/test_api.py tests/gateway/test_websocket.py
git commit -m "feat: add paired device gateway and durable dispatch"
```

### Task 5: Add Android pairing/settings UI without coupling connector lifetime to UI

**Files:**
- Create: `app/services/pairingClient.py`
- Modify: `app/screens/settings.py`
- Modify: `app/main.py`
- Test: `tests/app/test_pairing_client.py`

**Interfaces:**
- Produces: `pair_device(gateway_url: str, pairing_code: str, device_id: str, device_name: str, timeout: int = 15) -> dict`
- Consumes: connector config helpers from Task 1
- UI fields: gateway URL, device name, pairing code, enabled toggle, connection/device status

- [ ] **Step 1: Write failing pairing client tests**

Mock HTTPS responses and assert normalized gateway URL, POST to `/api/v1/devices/pair`, timeout behavior, rejection of non-HTTPS URL in production mode, safe handling of 4xx/5xx, and no credential content in exceptions.

- [ ] **Step 2: Run pairing client tests and verify failure**

Run: `python -m pytest tests/app/test_pairing_client.py -v`
Expected: FAIL because pairing client does not exist.

- [ ] **Step 3: Implement pairing client**

Use standard-library HTTPS (`urllib.request`) so the Android dependency set does not need another HTTP client. Return only parsed safe fields plus the one-time credential to the caller for immediate app-private persistence.

- [ ] **Step 4: Extend Settings UI**

Add a `Remote Gateway` section with URL, device name, pairing code input, `Pair Device` button, connector enable switch, read-only device id, and clear text states: `Not paired`, `Paired / connector disabled`, `Connecting`, `Online`, `Offline`.

- [ ] **Step 5: Wire Kivy callbacks in `app/main.py`**

Persist settings through `connectorConfig`; execute network pairing on a background thread; clear the pairing code field after use; never display the device credential; communicate status through non-secret state values shared via the existing app/service request-response files.

- [ ] **Step 6: Run Task 5 tests and syntax checks**

Run: `python -m pytest tests/app/test_pairing_client.py tests/app/test_connector_config.py -v`
Expected: PASS.

Run: `python -m py_compile app/main.py app/screens/settings.py app/services/pairingClient.py`
Expected: exit 0.

- [ ] **Step 7: Commit Task 5**

```bash
git add app/services/pairingClient.py app/screens/settings.py app/main.py tests/app/test_pairing_client.py
git commit -m "feat: add remote gateway pairing settings"
```

### Task 6: End-to-end integration tests for queue, reconnect and duplicate suppression

**Files:**
- Create: `tests/integration/test_remote_delivery.py`
- Modify only if test gaps reveal a defect: gateway/app connector files from Tasks 1-5

**Interfaces:**
- Consumes: FastAPI gateway test client, in-memory/fake SMS sender, Android `RemoteConnector`
- Produces: proof of the complete v1 protocol without requiring a real SIM

- [ ] **Step 1: Write end-to-end happy-path test**

Pair a fake Android device, establish its connector, submit `POST /api/v1/messages`, assert storage `queued -> dispatching -> acknowledged -> sent`, assert fake SMS sender called exactly once with destination/text, and verify `GET /api/v1/messages/{id}` reports `sent`.

- [ ] **Step 2: Write offline/reconnect test**

Submit while device is offline, assert durable `waiting_device`/queued state, reconnect the device, assert dispatch and terminal `sent` without re-submission from the client.

- [ ] **Step 3: Write gateway restart recovery test**

Persist a pending message, reconstruct gateway/store from the same SQLite file, reconnect device, and prove pending work is rediscovered.

- [ ] **Step 4: Write uncertain duplicate suppression test**

Simulate loss after Android marks `sending` but before a final result reaches the gateway; force redispatch of same `job_id`; assert SMS sender is not called a second time and gateway receives `duplicate_suppressed_uncertain` rather than duplicate transmission.

- [ ] **Step 5: Run integration suite and fix only observed defects**

Run: `python -m pytest tests/integration/test_remote_delivery.py -v`
Expected: PASS.

- [ ] **Step 6: Run complete Python test suite**

Run: `python -m pytest tests -q`
Expected: all tests PASS, zero failures.

- [ ] **Step 7: Commit Task 6**

```bash
git add tests/integration/test_remote_delivery.py app gateway
git commit -m "test: prove remote sms queue and reconnect flow"
```

### Task 7: Package deployment, CI, operator docs and final gates

**Files:**
- Create: `gateway/Dockerfile`
- Create: `gateway/docker-compose.yml`
- Create: `gateway/.env.example`
- Create: `.github/workflows/test.yml`
- Create: `.github/workflows/android-debug-apk.yml`
- Modify: `README.md`
- Modify: `docs/remote-connector-v1.md`

**Interfaces:**
- Consumes: completed Android/gateway implementation
- Produces: repeatable gateway deployment, automated Python tests, Android debug APK build workflow, operator setup instructions

- [ ] **Step 1: Add container deployment with persistent data volume**

`gateway/Dockerfile` runs Uvicorn on `0.0.0.0:8080`; compose mounts `./data:/app/data`, loads `.env`, and leaves TLS termination to a documented reverse proxy. Production docs require public HTTPS/WSS on TCP/443.

- [ ] **Step 2: Add safe environment template**

`.env.example` contains variable names and placeholders only, including `OPENSMS_API_TOKEN`, `OPENSMS_ADMIN_TOKEN`, `OPENSMS_DB_PATH=/app/data/opensms-gateway.sqlite3`, and `OPENSMS_PAIRING_TTL_SECONDS=300`.

- [ ] **Step 3: Add Python CI workflow**

Workflow installs `requirements-dev.txt`, `app/requirements.txt`, and `gateway/requirements.txt`, then runs `python -m pytest tests -q` and `python -m py_compile` on modified Python modules.

- [ ] **Step 4: Add Android debug APK build workflow**

Use a pinned Ubuntu runner, Java 17 and Buildozer dependencies already documented by the repository; run from `app/`; upload the generated debug APK as a workflow artifact. Do not sign a release APK or store signing secrets in this v1 branch.

- [ ] **Step 5: Update README/operator documentation**

Document: gateway deployment, reverse-proxy requirement, token generation, creating a pairing code, pairing the phone, enabling connector, sending a remote message, checking status, revoking a device, local `/sms/` fallback, and explicit Wi-Fi/4G/5G field-validation procedure.

- [ ] **Step 6: Run final static/test gates locally or in CI**

Run: `python -m pytest tests -q`
Expected: PASS.

Run: `python -m py_compile app/main.py app/services/*.py gateway/opensms_gateway/*.py gateway/run.py`
Expected: exit 0.

Run: `git diff --check main...feature/remote-connector-v1`
Expected: no whitespace errors.

- [ ] **Step 7: Confirm CI results and APK artifact**

Expected: Python test workflow green; Android debug build workflow green; debug APK artifact present. If the Android build fails, fix the build before making the PR ready for review.

- [ ] **Step 8: Physical-device acceptance gate**

On a paired Android phone with `SEND_SMS` permission: validate one remote SMS over a Wi-Fi network different from the gateway, then disconnect Wi-Fi and repeat over 4G/5G. Confirm gateway final state `sent` for both. This field test cannot be replaced by unit tests.

- [ ] **Step 9: Final security review**

Inspect logs and repository diff to prove no API token, admin token, pairing code, device credential, SMS body or recipient phone number is committed or unnecessarily logged. Confirm connector protocol still has no arbitrary-command capability.

- [ ] **Step 10: Commit Task 7**

```bash
git add gateway/Dockerfile gateway/docker-compose.yml gateway/.env.example .github/workflows/test.yml .github/workflows/android-debug-apk.yml README.md docs/remote-connector-v1.md
git commit -m "docs: package and validate remote gateway v1"
```

## Completion Criteria

The v1 is complete only when all automated tests pass, CI is green, an Android debug APK builds, the draft PR contains no secrets, and the physical-device Wi-Fi plus 4G/5G acceptance gate succeeds. Until the physical-device gate is performed, report the implementation as code-complete but not field-validated.
