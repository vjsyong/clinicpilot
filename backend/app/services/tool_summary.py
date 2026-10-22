"""Compact, user-facing summaries for assistant tool results."""

from __future__ import annotations

from typing import Any

from app.contracts import SourceRef


def tool_summary(name: str, payload: dict[str, Any]) -> str:
    if payload.get("ok") is False:
        return str(payload.get("error") or "failed")
    results = payload.get("results")
    if isinstance(results, list):
        return f"{len(results)} source{'s' if len(results) != 1 else ''}"
    bookings = payload.get("bookings")
    if isinstance(bookings, list):
        return f"{len(bookings)} booking{'s' if len(bookings) != 1 else ''}"
    booking = payload.get("booking")
    if isinstance(booking, dict):
        booking_id = str(booking.get("booking_id") or "").strip()
        return f"booking {booking_id}".strip()
    if name == "get_patient_record":
        return "patient record"
    if name == "update_booking_draft":
        return "draft updated"
    if name == "abandon_booking_draft":
        return "draft cancelled"
    return "ok"


def result_sources(payload: dict[str, Any]) -> list[SourceRef]:
    results = payload.get("results")
    if not isinstance(results, list):
        return []
    sources: list[SourceRef] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        source_file = item.get("source_file")
        record_id = item.get("record_id")
        if isinstance(source_file, str) and isinstance(record_id, str):
            sources.append(SourceRef(source_file=source_file, record_id=record_id))
    return sources
