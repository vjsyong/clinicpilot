from __future__ import annotations

import pytest
from app.agent.schemas import (
    TOOL_NAMES,
    TOOL_SCHEMAS,
    ToolValidationError,
    UnknownToolError,
    tool_definitions,
    validate_tool_arguments,
)


def test_exact_tool_surface() -> None:
    assert set(TOOL_NAMES) == {
        "search_knowledge",
        "get_patient_bookings",
        "update_booking_draft",
        "abandon_booking_draft",
        "create_booking",
    }
    assert len(tool_definitions()) == 5
    for name, schema in TOOL_SCHEMAS.items():
        assert schema["name"] == name
        assert schema["parameters"]["additionalProperties"] is False


def test_create_booking_takes_no_arguments() -> None:
    assert validate_tool_arguments("create_booking", "{}") == {}
    with pytest.raises(ToolValidationError):
        validate_tool_arguments("create_booking", '{"patient_id":"P002"}')


def test_unknown_tool_name_is_rejected() -> None:
    with pytest.raises(UnknownToolError):
        validate_tool_arguments("drop_tables", "{}")
    with pytest.raises(UnknownToolError):
        tool_definitions(["not_a_tool"])


def test_malformed_json_is_rejected() -> None:
    with pytest.raises(ToolValidationError):
        validate_tool_arguments("search_knowledge", "{not json")
    with pytest.raises(ToolValidationError):
        validate_tool_arguments("search_knowledge", '"just a string"')
    with pytest.raises(ToolValidationError):
        validate_tool_arguments("search_knowledge", "{}")


def test_search_knowledge_validation() -> None:
    parsed = validate_tool_arguments(
        "search_knowledge",
        '{"query":"  knee pain  ","filters":{"source_file":"doctors.csv"}}',
    )
    assert parsed == {
        "query": "knee pain",
        "filters": {"source_file": "doctors.csv"},
    }
    with pytest.raises(ToolValidationError):
        validate_tool_arguments("search_knowledge", '{"query":42}')
    with pytest.raises(ToolValidationError):
        validate_tool_arguments("search_knowledge", '{"query":"x","filters":{"source_file":1}}')
    with pytest.raises(ToolValidationError):
        validate_tool_arguments("search_knowledge", '{"query":"x","extra":true}')


def test_draft_update_validation() -> None:
    parsed = validate_tool_arguments(
        "update_booking_draft",
        '{"doctor_id":"D101","local_date":"2026-11-05","local_time":"09:00"}',
    )
    assert parsed["doctor_id"] == "D101"
    assert parsed["local_date"] == "2026-11-05"
    assert parsed["local_time"] == "09:00"

    assert validate_tool_arguments("update_booking_draft", '{"notes":null}') == {"notes": None}

    for bad in (
        '{"local_date":"tomorrow"}',
        '{"local_time":"9am"}',
        '{"doctor_id":"doctor-one"}',
        '{"patient_id":"P002"}',
        '{"notes":123}',
    ):
        with pytest.raises(ToolValidationError):
            validate_tool_arguments("update_booking_draft", bad)


def test_no_argument_tools_reject_extras() -> None:
    for name in ("get_patient_bookings", "abandon_booking_draft"):
        assert validate_tool_arguments(name, "") == {}
        with pytest.raises(ToolValidationError):
            validate_tool_arguments(name, '{"patient_id":"P002"}')
