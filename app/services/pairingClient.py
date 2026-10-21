import json
import os
from urllib import error, parse, request


class PairingError(RuntimeError):
    """Safe pairing error. Exception text never includes response bodies or credentials."""


def _pair_url(gateway_url: str) -> str:
    raw = str(gateway_url or "").strip().rstrip("/")
    parsed = parse.urlparse(raw)
    allow_insecure = os.environ.get("OPENSMS_ALLOW_INSECURE_GATEWAY") == "1"
    if parsed.scheme != "https" and not (allow_insecure and parsed.scheme == "http"):
        raise ValueError("Gateway URL must use HTTPS")
    if not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("Invalid gateway URL")
    base_path = parsed.path.rstrip("/")
    path = base_path if base_path.endswith("/api/v1/devices/pair") else base_path + "/api/v1/devices/pair"
    return parse.urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))


def pair_device(gateway_url: str, pairing_code: str, device_id: str, device_name: str, timeout: int = 15) -> dict:
    url = _pair_url(gateway_url)
    payload = json.dumps({"pairing_code": str(pairing_code).strip(), "device_id": str(device_id).strip(), "name": str(device_name).strip()}).encode("utf-8")
    req = request.Request(url, data=payload, method="POST", headers={"Content-Type": "application/json", "Accept": "application/json"})
    try:
        with request.urlopen(req, timeout=int(timeout)) as response:
            body = response.read()
    except error.HTTPError as exc:
        raise PairingError(f"gateway rejected pairing (HTTP {exc.code})") from None
    except (error.URLError, TimeoutError, OSError):
        raise PairingError("gateway unavailable") from None
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        raise PairingError("invalid gateway response") from None
    if not isinstance(data, dict):
        raise PairingError("invalid gateway response")
    returned_id = data.get("device_id")
    credential = data.get("device_credential")
    if returned_id != str(device_id).strip() or not isinstance(credential, str) or not credential:
        raise PairingError("invalid gateway response")
    return {"device_id": returned_id, "device_credential": credential}
