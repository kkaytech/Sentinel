"""Argon2id password hashing (NFR-002)."""

from __future__ import annotations

from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_PASSWORD_LENGTH = 12

_hasher = PasswordHasher()  # argon2-cffi defaults: Argon2id


def hash_password(password: str) -> str:
    return str(_hasher.hash(password))


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return bool(_hasher.verify(password_hash, password))
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return bool(_hasher.check_needs_rehash(password_hash))


@lru_cache(maxsize=1)
def dummy_hash() -> str:
    """A hash to verify against when the user does not exist, so timing does not reveal it."""
    return hash_password("sentinel-dummy-password-not-a-real-account")
