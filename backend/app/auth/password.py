"""Argon2id password hashing and the documented development password."""

from __future__ import annotations

import getpass
import sys
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.settings import DEV_PASSWORD, Settings

_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
)


def hash_password(password: str) -> str:
    return _HASHER.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    try:
        return _HASHER.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


@lru_cache(maxsize=1)
def _development_hash() -> str:
    return hash_password(DEV_PASSWORD)


def effective_password_hash(settings: Settings) -> str:
    if settings.demo_password_hash:
        return settings.demo_password_hash
    if settings.is_production:
        raise RuntimeError("DEMO_PASSWORD_HASH must be set in production")
    return _development_hash()


def main() -> None:
    password = getpass.getpass("New demo password: ")
    confirm = getpass.getpass("Repeat password: ")
    if not password:
        print("Password must not be empty.", file=sys.stderr)
        raise SystemExit(1)
    if password != confirm:
        print("Passwords do not match.", file=sys.stderr)
        raise SystemExit(1)
    print(hash_password(password))


if __name__ == "__main__":
    main()
