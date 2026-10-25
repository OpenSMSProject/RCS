import hashlib
import secrets

from pwdlib import PasswordHash


_PASSWORD_HASH = PasswordHash.recommended()


def hash_password(password: str) -> str:
    if not isinstance(password, str) or len(password) < 8:
        raise ValueError("password must contain at least 8 characters")
    return _PASSWORD_HASH.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    if not isinstance(password, str) or not isinstance(encoded, str) or not encoded:
        return False
    try:
        return bool(_PASSWORD_HASH.verify(password, encoded))
    except Exception:
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(48)


def hash_session_token(token: str) -> str:
    if not isinstance(token, str) or not token:
        raise ValueError("session token is required")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
