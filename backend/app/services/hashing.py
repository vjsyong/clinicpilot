"""Canonical JSON and request hashing shared by chat and booking idempotency."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
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


def canonical_booking_hash(
    *,
    patient_id: str,
    doctor_id: str,
    treatment_id: str,
    local_date: str,
    local_time: str,
    timezone: str,
    starts_at_utc: datetime,
    notes: str | None,
) -> str:
    """Hash the immutable canonical booking details, not just the operation id."""
    normalized_starts_at = (
        starts_at_utc.astimezone(UTC) if starts_at_utc.tzinfo else starts_at_utc.replace(tzinfo=UTC)
    )
    return sha256_hex(
        canonical_json(
            {
                "patient_id": patient_id,
                "doctor_id": doctor_id,
                "treatment_id": treatment_id,
                "local_date": local_date,
                "local_time": local_time,
                "timezone": timezone,
                "starts_at_utc": normalized_starts_at.isoformat(),
                "notes": notes,
            }
        )
    )
