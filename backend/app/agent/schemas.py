"""Strict tool schemas and local argument validation.

The model proposes tool calls; this module is the boundary that decides whether
a name and argument object are acceptable. The JSON schemas are sent to the
provider, and the hand-written validator enforces the same rules locally (the
provider is not trusted to enforce them).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from typing import Any

type QueryFilters = dict[str, str]

MAX_QUERY_CHARS = 500
MAX_NOTES_CHARS = 2000
MAX_FILTERS = 8

_DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
_TIME_PATTERN = r"^(?:[01]\d|2[0-3]):[0-5]\d$"
_ID_PATTERN = r"^[A-Z]\d{3}$"
_BOOKING_ID_PATTERN = r"^B\d{4}$"

_DATE_RE = re.compile(_DATE_PATTERN)
_TIME_RE = re.compile(_TIME_PATTERN)
_ID_RE = re.compile(_ID_PATTERN)
_BOOKING_ID_RE = re.compile(_BOOKING_ID_PATTERN)


class ToolValidationError(ValueError):
    """A tool call is unknown or its arguments are malformed."""


class UnknownToolError(ToolValidationError):
    """The model asked for a tool that is not part of the public surface."""


TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "search_knowledge": {
        "name": "search_knowledge",
        "description": (
            "Search the clinic knowledge base for clinics, doctors, treatments, "
            "hours, policies, fees, and preparation instructions. Always use this "
            "tool before stating clinic facts."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": MAX_QUERY_CHARS,
                    "description": "Natural-language or exact-name search query.",
                },
                "filters": {
                    "type": "object",
                    "description": "Optional exact-match filters.",
                    "additionalProperties": {"type": "string"},
                    "maxProperties": MAX_FILTERS,
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    "get_patient_bookings": {
        "name": "get_patient_bookings",
        "description": (
            "Read P001's current appointments from the internal booking API. "
            "Use this instead of relying on memory or patient history."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    "update_booking_draft": {
        "name": "update_booking_draft",
        "description": (
            "Create or change the current booking draft. Supply only fields the "
            "patient changed. Passing null clears a field. The server validates "
            "the values and returns missing fields or a canonical summary."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "booking_id": {
                    "type": ["string", "null"],
                    "pattern": _BOOKING_ID_PATTERN,
                    "description": (
                        "Existing booking ID to edit, e.g. B1001. The server prefills "
                        "the current details and requires a fresh confirmation."
                    ),
                },
                "doctor_id": {
                    "type": ["string", "null"],
                    "pattern": _ID_PATTERN,
                    "description": "Doctor ID from the knowledge tool, e.g. D101.",
                },
                "treatment_id": {
                    "type": ["string", "null"],
                    "pattern": _ID_PATTERN,
                    "description": "Treatment ID from the knowledge tool, e.g. T001.",
                },
                "local_date": {
                    "type": ["string", "null"],
                    "pattern": _DATE_PATTERN,
                    "description": "Appointment date in YYYY-MM-DD format.",
                },
                "local_time": {
                    "type": ["string", "null"],
                    "pattern": _TIME_PATTERN,
                    "description": "24-hour local time in HH:MM format.",
                },
                "notes": {
                    "type": ["string", "null"],
                    "maxLength": MAX_NOTES_CHARS,
                    "description": "Optional patient notes.",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    "delete_patient_booking": {
        "name": "delete_patient_booking",
        "description": (
            "Request removal of one of P001's bookings from the active list. The "
            "server requires explicit patient confirmation before deleting; the "
            "audit record is retained. Use the exact booking ID returned by "
            "get_patient_bookings."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "booking_id": {
                    "type": "string",
                    "pattern": _BOOKING_ID_PATTERN,
                    "description": "Booking ID to remove, e.g. B1001.",
                }
            },
            "required": ["booking_id"],
            "additionalProperties": False,
        },
    },
    "request_demo_reset": {
        "name": "request_demo_reset",
        "description": (
            "Ask to reset the shared demo workspace to its seed state. The "
            "application requires explicit confirmation and will clear chats and "
            "drafts while retaining the audit."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    "abandon_booking_draft": {
        "name": "abandon_booking_draft",
        "description": "Cancel the current booking draft at the patient's request.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    "create_booking": {
        "name": "create_booking",
        "description": (
            "Create the booking for the server-authorized draft. Takes no arguments. "
            "Only available after the patient confirms the exact canonical summary."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
}

TOOL_NAMES: tuple[str, ...] = tuple(TOOL_SCHEMAS)
CONFIRMATION_TOOL = "create_booking"


def tool_definitions(include: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """Return provider-ready function definitions in a stable order."""
    names = TOOL_NAMES if include is None else tuple(include)
    definitions: list[dict[str, Any]] = []
    for name in names:
        schema = TOOL_SCHEMAS.get(name)
        if schema is None:
            raise UnknownToolError(f"Unknown tool: {name}")
        definitions.append({"type": "function", "function": schema})
    return definitions


def validate_tool_arguments(name: str, arguments: str | Mapping[str, Any]) -> dict[str, Any]:
    """Validate a tool name and its arguments, returning a fresh argument dict.

    ``arguments`` is normally the raw JSON string supplied by the provider. A
    mapping is accepted for deterministic tests.
    """
    if name not in TOOL_SCHEMAS:
        raise UnknownToolError(f"Unknown tool: {name}")

    parsed = _decode_arguments(arguments)
    if name in {
        "get_patient_bookings",
        "abandon_booking_draft",
        "create_booking",
        "request_demo_reset",
    }:
        _reject_unknown_keys(name, parsed, set())
        return {}
    if name == "delete_patient_booking":
        return _validate_delete_booking(parsed)

    if name == "search_knowledge":
        return _validate_search(parsed)
    return _validate_draft_update(parsed)


def _decode_arguments(arguments: str | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(arguments, Mapping):
        return dict(arguments)
    if not isinstance(arguments, str):
        raise ToolValidationError("Tool arguments must be a JSON object.")
    text = arguments.strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ToolValidationError("Tool arguments are not valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise ToolValidationError("Tool arguments must be a JSON object.")
    return parsed


def _reject_unknown_keys(name: str, values: Mapping[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(values).difference(allowed))
    if unknown:
        joined = ", ".join(unknown)
        raise ToolValidationError(f"Unsupported argument(s) for {name}: {joined}.")


def _require_string(name: str, value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise ToolValidationError(f"{name}.{field} must be a string.")
    return value


def _optional_string(name: str, value: Any, *, field: str) -> str | None:
    if value is None:
        return None
    return _require_string(name, value, field=field)


def _validate_search(values: dict[str, Any]) -> dict[str, Any]:
    _reject_unknown_keys("search_knowledge", values, {"query", "filters"})
    if "query" not in values:
        raise ToolValidationError("search_knowledge.query is required.")
    query = _require_string("search_knowledge", values["query"], field="query").strip()
    if not query:
        raise ToolValidationError("search_knowledge.query must not be empty.")
    if len(query) > MAX_QUERY_CHARS:
        raise ToolValidationError(
            f"search_knowledge.query must be at most {MAX_QUERY_CHARS} characters."
        )

    filters_value = values.get("filters")
    filters: dict[str, str] | None = None
    if filters_value is not None:
        if not isinstance(filters_value, dict):
            raise ToolValidationError("search_knowledge.filters must be an object.")
        if len(filters_value) > MAX_FILTERS:
            raise ToolValidationError(
                f"search_knowledge.filters supports at most {MAX_FILTERS} entries."
            )
        filters = {}
        for key, value in filters_value.items():
            if not isinstance(key, str) or not key:
                raise ToolValidationError("search_knowledge.filters keys must be strings.")
            if not isinstance(value, str):
                raise ToolValidationError("search_knowledge.filters values must be strings.")
            filters[key] = value

    result: dict[str, Any] = {"query": query}
    if filters is not None:
        result["filters"] = filters
    return result


def _validate_delete_booking(values: dict[str, Any]) -> dict[str, Any]:
    _reject_unknown_keys("delete_patient_booking", values, {"booking_id"})
    booking_id = _require_string(
        "delete_patient_booking", values.get("booking_id"), field="booking_id"
    ).strip()
    if not _BOOKING_ID_RE.fullmatch(booking_id):
        raise ToolValidationError("delete_patient_booking.booking_id must look like B1001.")
    return {"booking_id": booking_id}


def _validate_draft_update(values: dict[str, Any]) -> dict[str, Any]:
    allowed = {"booking_id", "doctor_id", "treatment_id", "local_date", "local_time", "notes"}
    _reject_unknown_keys("update_booking_draft", values, allowed)

    normalized: dict[str, Any] = {}
    for field in ("booking_id", "doctor_id", "treatment_id", "local_date", "local_time", "notes"):
        if field not in values:
            continue
        value = _optional_string("update_booking_draft", values[field], field=field)
        if value is not None:
            value = value.strip()
            if not value:
                value = None
        normalized[field] = value

    for field in ("doctor_id", "treatment_id"):
        value = normalized.get(field)
        if value is not None and not _ID_RE.fullmatch(value):
            raise ToolValidationError(f"update_booking_draft.{field} must look like D101 or T001.")
    booking_id = normalized.get("booking_id")
    if booking_id is not None and not _BOOKING_ID_RE.fullmatch(booking_id):
        raise ToolValidationError("update_booking_draft.booking_id must look like B1001.")
    local_date = normalized.get("local_date")
    if local_date is not None and not _DATE_RE.fullmatch(local_date):
        raise ToolValidationError("update_booking_draft.local_date must be in YYYY-MM-DD format.")
    local_time = normalized.get("local_time")
    if local_time is not None and not _TIME_RE.fullmatch(local_time):
        raise ToolValidationError("update_booking_draft.local_time must be a 24-hour HH:MM time.")
    notes = normalized.get("notes")
    if notes is not None and len(notes) > MAX_NOTES_CHARS:
        raise ToolValidationError(
            f"update_booking_draft.notes must be at most {MAX_NOTES_CHARS} characters."
        )
    return normalized
