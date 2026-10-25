import hashlib
import secrets

from pwdlib import PasswordHash


_PASSWORD_HASH = PasswordHash.recommended()


def hash_password(password: str) -> str:
    if not isinstance(password, str) or not password:
        raise ValueError("password is required")
    return _PASSWORD_HASH.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    try:
        return bool(_PASSWORD_HASH.verify(password, encoded))
    except Exception:
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    if not isinstance(token, str) or not token:
        raise ValueError("session token is required")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
