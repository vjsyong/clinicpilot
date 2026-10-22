"""Canonical JSON and request hashing shared by chat and booking idempotency."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def chat_request_hash(message: str, patient_id: str) -> str:
    return sha256_hex(canonical_json({"message": message, "patient_id": patient_id}))


def booking_request_hash(draft_id: str, draft_version: int) -> str:
    return sha256_hex(canonical_json({"draft_id": draft_id, "draft_version": draft_version}))
