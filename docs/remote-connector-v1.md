# OpenSMS Remote Connector v1

The Remote Connector lets an Android phone running OpenSMS send SMS jobs from any Internet connection. The phone initiates an outbound encrypted WebSocket connection to a central gateway, so the phone does **not** need a public IP, an inbound port, or to share a LAN with the API client.

The original local `POST /sms/` API on port `9292` remains available as an optional local fallback.

## Architecture

```text
API client --HTTPS/443--> reverse proxy --HTTP/loopback--> OpenSMS Gateway
                                                        |
Android phone <---------------- WSS/443 ----------------+
     |
  SmsManager
     |
    SIM
```

Remote protocol frames are limited to `hello`, `heartbeat`, `ping/pong`, `job`, `job_ack`, and `job_result`. There is no remote shell, file execution, generic tunnel, or arbitrary-command endpoint.

## 1. Deploy the gateway

The supplied Compose file binds the application to `127.0.0.1:8080`. Put Caddy, Nginx, Traefik, Cloudflare Tunnel, or another trusted TLS reverse proxy in front of it and publish **HTTPS/WSS on TCP 443**.

```bash
cd gateway
cp .env.example .env
mkdir -p data
sudo chown 10001:10001 data
```

Generate two different high-entropy tokens:

```bash
python3 - <<'PY'
import secrets
print("OPENSMS_API_TOKEN=osmsapi_" + secrets.token_urlsafe(32))
print("OPENSMS_ADMIN_TOKEN=osmsadmin_" + secrets.token_urlsafe(32))
PY
```

Put them in `gateway/.env`. Never commit `.env`.

```bash
docker compose up -d --build
curl http://127.0.0.1:8080/healthz
curl http://127.0.0.1:8080/readyz
```

Example Caddy config:

```caddy
sms.example.com {
    reverse_proxy 127.0.0.1:8080
}
```

Do not expose port `8080` publicly. Production Android pairing rejects plaintext `http://`/`ws://`; insecure transport is available only for explicit development with `OPENSMS_ALLOW_INSECURE_GATEWAY=1`.

## 2. Pair a phone

Create a one-time code:

```bash
curl -sS -X POST https://sms.example.com/api/v1/pairing-codes \
  -H "Authorization: Bearer $OPENSMS_ADMIN_TOKEN"
```

In OpenSMS open **Settings → Remote Gateway**, enter the HTTPS gateway URL, device name, and six-digit code, then tap **Pair Device**. The credential is stored only in app-private storage and is never displayed. Enable **Remote Connector**.

Expected states: `Not paired`, `Paired / connector disabled`, `Connecting`, `Online`, `Offline`.

## 3. Send remotely

```bash
curl -sS -X POST https://sms.example.com/api/v1/messages \
  -H "Authorization: Bearer $OPENSMS_API_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: order-123-sms-1" \
  -d '{"device_id":"osms-abcdef123456","to":"+5561999999999","text":"Teste OpenSMS remoto"}'
```

Check status with `GET /api/v1/messages/{message_id}`. States are `queued`, `waiting_device`, `dispatching`, `acknowledged`, `sent`, `failed`. A stable `Idempotency-Key` prevents a client retry from creating a second job.

## 4. Revoke a device

```bash
curl -i -X DELETE https://sms.example.com/api/v1/devices/osms-abcdef123456 \
  -H "Authorization: Bearer $OPENSMS_ADMIN_TOKEN"
```

Revocation invalidates the device credential and disconnects the current session.

## 5. Queue and duplicate safety

Jobs are durable in SQLite. Offline phones stay in `waiting_device` and receive work after reconnect. Android keeps a bounded persistent ledger keyed by `job_id`; a job left in `sending` becomes `ambiguous` after restart and is rejected as `duplicate_suppressed_uncertain` rather than risking a second carrier submission. Pairing and message endpoints are rate-limited, and stale device sessions are closed when heartbeat stops.

## 6. Local fallback

The original local `/sms/` API remains available on port `9292`. It is separate from the gateway and must not be exposed directly to the public Internet.

## 7. Required physical-device acceptance gate

Before calling v1 field-validated:

1. Install the debug APK produced by GitHub Actions.
2. Grant SMS/notification/restricted permissions.
3. Pair to the public HTTPS gateway.
4. Send one SMS while the phone is on Wi-Fi different from the gateway; state must end `sent`.
5. Disable Wi-Fi and repeat over 4G/5G; state must end `sent`.
6. Cut connectivity, submit a message, restore connectivity, and verify queued delivery without a duplicate.

Automated tests do not replace this SIM/network test.

## Security checklist

- Never commit `.env`, API/admin tokens, pairing codes, or device credentials.
- Do not log SMS bodies or recipient numbers.
- Expose only HTTPS/WSS 443 through a trusted reverse proxy; keep 8080 private.
- Use distinct API/admin tokens and revoke lost phones immediately.
- The v1 protocol intentionally has no arbitrary command execution capability.
