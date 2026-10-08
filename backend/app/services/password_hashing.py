from __future__ import annotations

import hashlib
import secrets

PBKDF2_ITERATIONS = 600_000
MAX_PBKDF2_ITERATIONS = 2_000_000


def sha256_hex(value: str) -> str:
    """Plain SHA-256 for random link tokens; passwords use PBKDF2 only."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_sha256(value: str, *, allow_empty: bool = False) -> str:
    """A stored token digest: 64 lowercase hex characters."""
    digest = str(value or "").strip().lower()
    if not digest and allow_empty:
        return ""
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError("token_sha256 values must be 64-character lowercase hex digests.")
    return digest


def hash_password(password: str, *, iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{iterations}${salt.hex()}${digest.hex()}"


def _parse_password_hash(encoded: str) -> tuple[int, bytes, bytes]:
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
    return iterations, salt, digest


def verify_password(password: str, encoded: str) -> bool:
    iterations, salt, expected = _parse_password_hash(encoded)
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return secrets.compare_digest(actual, expected)


def validate_password_hash(encoded: str) -> None:
    _, salt, digest = _parse_password_hash(encoded)
    if not any(salt) or not any(digest):
        raise ValueError("PBKDF2 password hash still contains placeholder values.")
