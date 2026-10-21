import base64
import hashlib
import secrets


PBKDF2_ITERATIONS = 210_000
SALT_BYTES = 16


def new_secret(prefix: str) -> str:
    if not prefix or any(ch.isspace() for ch in prefix):
        raise ValueError("invalid secret prefix")
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def hash_secret(secret: str) -> str:
    if not isinstance(secret, str) or not secret:
        raise ValueError("secret is required")
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PBKDF2_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def verify_secret(secret: str, encoded: str) -> bool:
    try:
        algorithm, iterations_s, salt_s, digest_s = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_s)
        salt = base64.urlsafe_b64decode(salt_s.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_s.encode("ascii"))
        actual = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt, iterations)
        return secrets.compare_digest(actual, expected)
    except (AttributeError, TypeError, ValueError, UnicodeError):
        return False
