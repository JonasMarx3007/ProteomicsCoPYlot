from __future__ import annotations

import hashlib
import secrets

PBKDF2_ITERATIONS = 600_000
MAX_PBKDF2_ITERATIONS = 2_000_000


def hash_password(password: str, *, iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    parts = str(encoded or "").strip().split("$")
    if len(parts) != 3:
        raise ValueError("PBKDF2 password hashes must use iterations$salt$hash format.")
    try:
        iterations = int(parts[0])
        salt = bytes.fromhex(parts[1])
        expected = bytes.fromhex(parts[2])
    except ValueError as exc:
        raise ValueError("PBKDF2 password hash is malformed.") from exc
    if iterations < 100_000 or iterations > MAX_PBKDF2_ITERATIONS or not salt or len(expected) != 32:
        raise ValueError("PBKDF2 password hash parameters are invalid.")
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return secrets.compare_digest(actual, expected)


def validate_password_hash(encoded: str) -> None:
    parts = str(encoded or "").strip().split("$")
    if len(parts) != 3:
        raise ValueError("PBKDF2 password hashes must use iterations$salt$hash format.")
    try:
        iterations = int(parts[0])
        salt = bytes.fromhex(parts[1])
        digest = bytes.fromhex(parts[2])
    except ValueError as exc:
        raise ValueError("PBKDF2 password hash is malformed.") from exc
    if iterations < 100_000 or iterations > MAX_PBKDF2_ITERATIONS or not salt or len(digest) != 32:
        raise ValueError("PBKDF2 password hash parameters are invalid.")
    if not any(salt) or not any(digest):
        raise ValueError("PBKDF2 password hash still contains placeholder values.")
