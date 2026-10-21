# OpenSMS/RCS Remote Connector v1

The Remote Connector lets an Android phone running OpenSMS/RCS send SMS jobs from any Internet connection. The phone initiates an outbound encrypted WebSocket connection to a central gateway, so the phone does **not** need a public IP, an inbound port, or to share a LAN with the API client.

The original local `POST /sms/` API on port `9292` remains available as an optional local fallback.

## Architecture

```text
API client --HTTPS/443--> reverse proxy --HTTP/loopback--> OpenSMS/RCS Gateway
                                                            |
Android phone <------------------ WSS/443 -------------------+
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

The current v1 transport is SMS. RCS remains a separate channel integration and must pass its own provider/device acceptance gates before being marked operational.
