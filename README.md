<p align="center"><img width="20%" src="app/data/images/favicont512.png" /></p>

# 📨 OpenSMS/RCS
**OpenSMS/RCS** is the project name for the Android messaging gateway, its central Remote Gateway, and the evolving multi-tenant SaaS communications control plane.

The current transport v1 implements SMS end to end. RCS is the next channel integration and is not represented as complete until its own provider/device gates pass.

An open-source solution to host a `SMS` API server locally, with an optional **Remote Gateway** that lets the Android phone work over Wi-Fi or mobile data without sharing the same LAN as the API client.

### Features
👉 Turns your Android phone into an SMS API server. <br>
👉 Optional outbound-only Remote Connector: no public IP or inbound port on the phone. <br>
👉 Durable remote queue, reconnect, per-device credentials, idempotency, and local `/sms/` fallback. <br>
👉 Phase 1 SaaS foundation: PF/PJ tenants, Owner/Admin/Operator RBAC, Super Admin, trial/plan entitlements, tenant API keys and PostgreSQL control-plane state. <br>
👉 Open-source, no advertisements and privacy focused.

## ☁️ SaaS Foundation — Phase 1

The feature branch introduces PostgreSQL **alongside** the existing SQLite gateway. It does not destructively migrate or replace existing Android device/message state.

Phase 1 provides:

- PF/CPF and PJ/CNPJ tenant boundaries;
- multiple tenant users with `Owner`, `Admin` and `Operator` roles;
- separate platform `Super Admin` controls with audit events;
- 7-day default trial and centralized entitlement model;
- separate PF/PJ plan catalogs;
- tenant-scoped API keys shown raw once and stored only as hashes;
- safe ownership mapping of existing SQLite Android devices into tenants;
- `/saas/v1/...` foundation APIs;
- PostgreSQL 16 migrations and readiness checks;
- migration-safe `install.sh` / `rcs update` flow.

See **[SaaS Foundation operator guide](docs/saas-foundation.md)** for deployment boundaries, security model, trial defaults, migrations and Phase 1 non-goals.

The production email-delivery adapter, tenant-aware SMS usage/metering, campaigns, billing providers, DeskCommCRM integration, RCS transport and WhatsApp adapters remain later phases.

## 🌐 Remote Gateway v1

The phone connects **outbound** to a central gateway over `wss://`/TCP 443. This works behind CGNAT and on unrelated Wi-Fi/4G/5G networks. The gateway is message-specific; it is not a general VPN or remote shell.

See **[Remote Connector v1 operator guide](docs/remote-connector-v1.md)** for Docker deployment, TLS/reverse proxy, pairing, remote send/status, device revocation, queue semantics and the required physical-device acceptance test.

```bash
curl -X POST https://sms.example.com/api/v1/messages \
  -H "Authorization: Bearer $OPENSMS_API_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: example-1" \
  -d '{"device_id":"osms-abcdef123456","to":"+5561999999999","text":"Hello from OpenSMS/RCS Remote Gateway"}'
```

## Local API

After installing the app and granting SMS permissions, start the local server and generate an API key.

```bash
curl -i -X POST 'http://127.0.0.1:9292/sms/' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer my-secret-api-key' \
  -d '{"number":"+1234567890","text":"Hello from OpenSMS/RCS API!"}'
```

Do not expose port `9292` directly to the public Internet.

## Tech stack

- FastAPI for local, gateway and SaaS foundation APIs
- KivyMD/Kivy for Android UI
- Android `SmsManager` through Pyjnius
- SQLite durable legacy gateway queue
- PostgreSQL 16 + SQLAlchemy/Alembic for SaaS control-plane state
- WebSocket (`wss://`) outbound Android connector

## Building Android

A Linux environment is recommended (WSL/VM also works):

```bash
sudo apt install -y ant autoconf automake ccache cmake g++ gcc lbzip2 libffi-dev libltdl-dev libtool libssl-dev make openjdk-17-jdk patch patchelf pkg-config unzip wget zip git python3 python3-venv python3-dev libcairo2-dev libjpeg-dev zlib1g-dev
git clone https://github.com/OpenSMSProject/RCS.git
cd RCS/app
python3 -m venv .env
source .env/bin/activate
pip install -r req_android.txt
buildozer android debug
```

GitHub Actions includes an **Android debug APK** workflow that uploads the generated APK as an artifact. Release signing is deliberately outside v1.
