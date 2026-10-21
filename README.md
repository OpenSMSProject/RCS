<p align="center"><img width="20%" src="app/data/images/favicont512.png" /></p>

# 📨 OpenSMS/RCS
**OpenSMS/RCS** is the project name for the Android messaging gateway and its central Remote Gateway.

The current v1 implements SMS end to end. RCS is the next channel integration and is not represented as complete until its own provider/device gates pass.

An open-source solution to host a `SMS` API server locally, with an optional **Remote Gateway** that lets the Android phone work over Wi-Fi or mobile data without sharing the same LAN as the API client.

### Features
👉 Turns your Android phone into an SMS API server. <br>
👉 Optional outbound-only Remote Connector: no public IP or inbound port on the phone. <br>
👉 Durable remote queue, reconnect, per-device credentials, idempotency, and local `/sms/` fallback. <br>
👉 Open-source, no advertisements and privacy focused.

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

- FastAPI for local and gateway APIs
- KivyMD/Kivy for Android UI
- Android `SmsManager` through Pyjnius
- SQLite durable gateway queue
- WebSocket (`wss://`) outbound Android connector

## Building Android

A Linux environment is recommended (WSL/VM also works):

```bash
sudo apt install -y ant autoconf automake ccache cmake g++ gcc lbzip2 libffi-dev libltdl-dev libtool libssl-dev make openjdk-17-jdk patch patchelf pkg-config unzip wget zip git python3 python3-venv python3-dev libcairo2-dev libjpeg-dev zlib1g-dev
git clone https://github.com/wesleiandersonti/OpenSMS.git
cd OpenSMS/app
python3 -m venv .env
source .env/bin/activate
pip install -r req_android.txt
buildozer android debug
```

GitHub Actions includes an **Android debug APK** workflow that uploads the generated APK as an artifact. Release signing is deliberately outside v1.
