# OpenSMS Remote Connector v1

Goal: allow an Android phone running OpenSMS to work from any network without exposing port 9292 or requiring the phone and client to share the same LAN.

## Architecture

- The Android device initiates an outbound encrypted connection to a central gateway.
- No public IP or inbound port is required on the phone.
- The existing local `/sms/` API remains available as a local fallback.
- Remote jobs use acknowledgements and results so queued messages are not lost when a device reconnects.

## Initial protocol

Device -> gateway:
- hello
- heartbeat
- job_ack
- job_result

Gateway -> device:
- ping
- job (send_sms)

## Delivery states

- queued
- waiting_device
- dispatching
- acknowledged
- sent
- failed

## Security

- TLS (`wss://`)
- per-device identity
- per-device credential
- no inbound listener required for remote operation
- no API key shared between all Android devices
