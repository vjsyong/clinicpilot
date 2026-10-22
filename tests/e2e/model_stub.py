#!/usr/bin/env python3
"""Deterministic OpenAI-compatible model stub for the ClinicPilot E2E harness.

This is intentionally stdlib-only: CI starts it next to the real application
container, so the browser test exercises the real agent controller, tool
execution, booking API and SQLite database. Only the external generation
provider is replaced.

The stub is stateless. Every response is derived from the message history and
the tool list supplied by the controller, which is exactly how the real
provider is called.

Endpoints:
    POST /v1/chat/completions
    POST /chat/completions
    GET  /healthz

Usage:
    python tests/e2e/model_stub.py --host 0.0.0.0 --port 9000

Never logs request bodies, tool payloads, or credentials.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

DEFAULT_MODEL = "clinicpilot-e2e-stub"
MAX_BODY_BYTES = 4 * 1024 * 1024

AFFIRMATIVES = {
    "yes",
    "yes please",
    "confirm",
    "confirmed",
    "go ahead",
    "book it",
    "yes book it",
    "yes confirm",
    "please book it",
}

KNEE_RE = re.compile(
    r"\b(knee|orthop[a-z]*|joint|sports?\s+injur[a-z]*)\b", re.IGNORECASE
)
BOOKING_RE = re.compile(
    r"\b(book|booking|appointment|consult[a-z]*|schedule|reserve)\b", re.IGNORECASE
)
HOURS_RE = re.compile(
    r"\b(hours?|open(?:ing)?|closed|policy|policies|cancel[a-z]*|insurance|fee|fees|price|prices|parking)\b",
    re.IGNORECASE,
)
BOOKINGS_LIST_RE = re.compile(
    r"\b(my|show|list|what|current|upcoming|any)\b.*\b(bookings?|appointments?)\b",
    re.IGNORECASE,
)

DRAFT_BASE = {
    "doctor_id": "D104",
    "treatment_id": "T005",
}
DRAFT_DEFAULT_SLOT = {
    "local_date": "2030-06-17",
    "local_time": "15:00",
}
DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
TIME_RE = re.compile(r"\b([01]\d|2[0-3]):([0-5]\d)\b")
CONSULT_RE = re.compile(r"\b(consultation|appointment|book|booking)\b", re.IGNORECASE)
BOOKING_ID_RE = re.compile(r"\b(B\d{4})\b")
EDIT_RE = re.compile(r"\bedit\b", re.IGNORECASE)
DRAFT_DOCTOR = "Dr. James Wilson"
DRAFT_TREATMENT = "Joint & Pain Consultation"


def _draft_arguments(text: str) -> dict[str, str]:
    arguments = dict(DRAFT_BASE)
    date_match = DATE_RE.search(text)
    time_match = TIME_RE.search(text)
    if date_match and time_match:
        arguments["local_date"] = date_match.group(1)
        arguments["local_time"] = f"{time_match.group(1)}:{time_match.group(2)}"
        return arguments
    if CONSULT_RE.search(text):
        arguments.update(DRAFT_DEFAULT_SLOT)
    return arguments


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower()).rstrip(".!?")


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            content = message.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return " ".join(
                    str(part.get("text", ""))
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                )
    return ""


def _tool_names(tools: Any) -> list[str]:
    if not isinstance(tools, list):
        return []
    names: list[str] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function")
        if isinstance(function, dict):
            name = function.get("name")
            if isinstance(name, str):
                names.append(name)
    return names


def _tool_history(
    messages: list[dict[str, Any]],
) -> tuple[set[str], list[dict[str, Any]]]:
    """Return tool names ever called plus the ordered tool results."""
    called: set[str] = set()
    call_names: dict[str, str] = {}
    results: list[dict[str, Any]] = []

    for message in messages:
        role = message.get("role")
        if role == "assistant":
            for call in message.get("tool_calls") or []:
                if not isinstance(call, dict):
                    continue
                function = call.get("function")
                if not isinstance(function, dict):
                    continue
                name = function.get("name")
                if isinstance(name, str):
                    called.add(name)
                    call_id = call.get("id")
                    if isinstance(call_id, str):
                        call_names[call_id] = name
        elif role == "tool":
            name = message.get("name")
            if not isinstance(name, str):
                name = call_names.get(str(message.get("tool_call_id")), "")
            results.append({"name": name, "content": message.get("content")})
    return called, results


def _parse_json(content: Any) -> Any:
    if isinstance(content, (dict, list)):
        return content
    if not isinstance(content, str):
        return None
    try:
        return json.loads(content)
    except (TypeError, ValueError):
        return None


def _booking_summary(content: Any) -> str:
    data = _parse_json(content)
    if isinstance(data, dict):
        for key in ("bookings", "items", "results"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    if not isinstance(data, list):
        return "I could not read the current bookings list. Please try refreshing."

    if not data:
        return "You have no current bookings."

    parts: list[str] = []
    for booking in data[:5]:
        if not isinstance(booking, dict):
            continue
        doctor = booking.get("doctor_name") or booking.get("doctor_id") or "a doctor"
        treatment = (
            booking.get("treatment_name")
            or booking.get("treatment_id")
            or "a consultation"
        )
        date = booking.get("local_date") or "an unknown date"
        clock = booking.get("local_time") or ""
        parts.append(f"{treatment} with {doctor} on {date} {clock}".strip())
    if not parts:
        return f"You have {len(data)} booking(s) on file."
    return "Here are your bookings: " + "; ".join(parts) + "."


def _draft_summary(content: Any) -> str:
    data = _parse_json(content)
    draft: dict[str, Any] = {}
    if isinstance(data, dict):
        candidate = data.get("draft")
        if isinstance(candidate, dict):
            draft = candidate
        elif "doctor_id" in data or "treatment_id" in data:
            draft = data

    if isinstance(data, dict) and data.get("errors"):
        errors = data.get("errors")
        if isinstance(errors, list):
            return "I could not update the booking draft: " + "; ".join(
                str(error) for error in errors
            )

    if isinstance(data, dict) and data.get("missing_fields"):
        missing = data.get("missing_fields")
        if isinstance(missing, list) and missing:
            return (
                "I still need these details: "
                + ", ".join(str(field) for field in missing)
                + "."
            )

    doctor = str(draft.get("doctor_name") or DRAFT_DOCTOR)
    treatment = str(draft.get("treatment_name") or DRAFT_TREATMENT)
    date = str(draft.get("local_date") or "not set")
    clock = str(draft.get("local_time") or "not set")
    return (
        f"Here is the appointment summary: {treatment} with {doctor} on {date} at {clock}. "
        "Shall I book it? Reply yes to confirm."
    )


def _knowledge_answer(content: Any) -> str:
    data = _parse_json(content)
    documents: list[dict[str, Any]] = []
    if isinstance(data, list):
        documents = [item for item in data if isinstance(item, dict)]
    elif isinstance(data, dict):
        for key in ("documents", "results", "items"):
            if isinstance(data.get(key), list):
                documents = [item for item in data[key] if isinstance(item, dict)]
                break

    if documents:
        text = str(documents[0].get("text", "")).strip()
        if text:
            if len(text) > 320:
                text = text[:317].rstrip() + "..."
            citation = documents[0].get("citation")
            suffix = f" {citation}" if isinstance(citation, str) and citation else ""
            return f"According to the clinic information: {text}{suffix}"
    return (
        "The clinic knowledge base has information about that question. "
        "Please contact the clinic if you need exact scheduling details."
    )


def _text_completion(text: str) -> dict[str, Any]:
    return {"content": text, "tool_calls": []}


def _tool_completion(
    name: str, arguments: dict[str, Any], index: int
) -> dict[str, Any]:
    return {
        "content": None,
        "tool_calls": [
            {
                "id": f"call_stub_{index}_{name}",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(arguments, separators=(",", ":")),
                },
            }
        ],
    }


def decide(messages: list[dict[str, Any]], tools: Any) -> dict[str, Any]:
    names = _tool_names(tools)
    name_set = set(names)
    called, results = _tool_history(messages)
    last = messages[-1] if messages else {}
    last_role = last.get("role")
    last_user = _last_user_text(messages)
    normalized_user = _normalize(last_user)
    last_tool = results[-1] if results and last_role == "tool" else None

    # The controller narrows the tool list to create_booking only after a valid
    # server-side confirmation. In that state there is exactly one valid move.
    if name_set == {"create_booking"}:
        if last_tool and last_tool.get("name") == "create_booking":
            return _text_completion(
                "Your appointment is booked and the bookings table has been refreshed."
            )
        return _tool_completion("create_booking", {}, len(results))

    if last_tool is not None:
        tool_name = last_tool.get("name")
        content = last_tool.get("content")
        if tool_name == "update_booking_draft":
            return _text_completion(_draft_summary(content))
        if tool_name == "get_patient_bookings":
            return _text_completion(_booking_summary(content))
        if tool_name == "search_knowledge":
            if KNEE_RE.search(last_user) or (
                BOOKING_RE.search(last_user) and not HOURS_RE.search(last_user)
            ):
                if "update_booking_draft" in name_set:
                    return _tool_completion(
                        "update_booking_draft", _draft_arguments(last_user), len(results)
                    )
                return _text_completion(
                    "I can help with that consultation. Which date and time would you prefer?"
                )
            return _text_completion(_knowledge_answer(content))
        if tool_name == "create_booking":
            return _text_completion(
                "Your appointment is booked and the bookings table has been refreshed."
            )
        if tool_name == "abandon_booking_draft":
            return _text_completion("The booking draft has been cancelled.")
        if tool_name == "delete_patient_booking":
            return _text_completion("I need one more confirmation before removing it.")
        if tool_name == "request_demo_reset":
            return _text_completion("The reset requires the confirmation card.")

    if normalized_user in AFFIRMATIVES and "create_booking" in name_set:
        return _tool_completion("create_booking", {}, len(results))

    if "reset" in normalized_user and "request_demo_reset" in name_set:
        return _tool_completion("request_demo_reset", {}, len(results))

    if (
        "delete" in normalized_user
        and BOOKING_ID_RE.search(last_user)
        and "delete_patient_booking" in name_set
    ):
        return _tool_completion(
            "delete_patient_booking",
            {"booking_id": BOOKING_ID_RE.search(last_user).group(1)},
            len(results),
        )

    edit_match = BOOKING_ID_RE.search(last_user)
    if edit_match and EDIT_RE.search(last_user) and "update_booking_draft" in name_set:
        return _tool_completion(
            "update_booking_draft",
            {"booking_id": edit_match.group(1)},
            len(results),
        )

    if (
        DATE_RE.search(last_user)
        and TIME_RE.search(last_user)
        and "update_booking_draft" in name_set
    ):
        return _tool_completion(
            "update_booking_draft", _draft_arguments(last_user), len(results)
        )

    wants_knee = bool(KNEE_RE.search(last_user))
    wants_booking = bool(BOOKING_RE.search(last_user))
    wants_hours = bool(HOURS_RE.search(last_user))
    wants_booking_list = bool(BOOKINGS_LIST_RE.search(last_user))

    if wants_booking_list and "get_patient_bookings" in name_set:
        return _tool_completion("get_patient_bookings", {}, len(results))

    if (wants_knee or wants_booking) and not wants_hours:
        if "update_booking_draft" in name_set and "search_knowledge" in called:
            return _tool_completion(
                "update_booking_draft", _draft_arguments(last_user), len(results)
            )
        if "search_knowledge" in name_set:
            return _tool_completion(
                "search_knowledge",
                {"query": "knee pain consultation orthopedics"},
                len(results),
            )
        if "update_booking_draft" in name_set:
            return _tool_completion(
                "update_booking_draft", _draft_arguments(last_user), len(results)
            )

    if wants_hours and "search_knowledge" in name_set:
        return _tool_completion(
            "search_knowledge",
            {"query": last_user[:200]},
            len(results),
        )

    return _text_completion(
        "I can help with clinic information, your bookings, or a consultation. "
        "What would you like to do?"
    )


def _completion_payload(
    model: str, decision: dict[str, Any], messages: list[dict[str, Any]]
) -> dict[str, Any]:
    tool_calls = decision["tool_calls"]
    message: dict[str, Any] = {"role": "assistant", "content": decision["content"]}
    if tool_calls:
        message["tool_calls"] = tool_calls
    prompt_chars = sum(len(str(item.get("content") or "")) for item in messages)
    return {
        "id": f"chatcmpl-stub-{int(time.time())}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": "tool_calls" if tool_calls else "stop",
            }
        ],
        "usage": {
            "prompt_tokens": max(1, prompt_chars // 4),
            "completion_tokens": max(1, len(json.dumps(message)) // 4),
            "total_tokens": max(1, (prompt_chars + len(json.dumps(message))) // 4),
        },
    }


class ModelStubHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ClinicPilotModelStub/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        # Method/path/status only; never request headers or bodies.
        sys.stderr.write(f"{self.log_date_time_string()} {fmt % args}\n")

    def _send_json(self, status: HTTPStatus | int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, status: int, message: str) -> None:
        self._send_json(
            status,
            {
                "error": {
                    "message": message,
                    "type": "invalid_request_error",
                    "param": None,
                    "code": "invalid_request",
                }
            },
        )

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            self._send_json(HTTPStatus.OK, {"status": "ok"})
            return
        if path in ("/v1/models", "/models"):
            self._send_json(
                HTTPStatus.OK,
                {
                    "object": "list",
                    "data": [
                        {
                            "id": DEFAULT_MODEL,
                            "object": "model",
                            "created": 0,
                            "owned_by": "clinicpilot-ci",
                        }
                    ],
                },
            )
            return
        self._send_error_json(HTTPStatus.NOT_FOUND, "not found")

    def _send_stream(
        self, model: str, decision: dict[str, Any], messages: list[dict[str, Any]]
    ) -> None:
        created = int(time.time())
        stream_id = f"chatcmpl-stub-{created}"

        def chunk(delta: dict[str, Any], finish_reason: str | None = None) -> str:
            payload = {
                "id": stream_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": delta,
                        "finish_reason": finish_reason,
                    }
                ],
            }
            return "data: " + json.dumps(payload, separators=(",", ":")) + "\n\n"

        frames: list[str] = []
        prompt_chars = sum(len(str(item.get("content") or "")) for item in messages)
        usage = {
            "prompt_tokens": max(1, prompt_chars // 4),
            "completion_tokens": max(1, len(json.dumps(decision)) // 4),
            "total_tokens": max(1, (prompt_chars + len(json.dumps(decision))) // 4),
        }
        content = decision.get("content")
        if isinstance(content, str) and content:
            frames.append(chunk({"role": "assistant", "content": content}))
        tool_calls = decision.get("tool_calls") or []
        if tool_calls:
            frames.append(chunk({"role": "assistant", "tool_calls": tool_calls}))
            frames.append(chunk({}, "tool_calls"))
        else:
            frames.append(chunk({}, "stop"))
        frames.append(
            "data: "
            + json.dumps(
                {
                    "id": stream_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [],
                    "usage": usage,
                },
                separators=(",", ":"),
            )
            + "\n\n"
        )
        frames.append("data: [DONE]\n\n")
        body = "".join(frames).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path not in ("/v1/chat/completions", "/chat/completions"):
            self._send_error_json(HTTPStatus.NOT_FOUND, "not found")
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid content length")
            return
        if length <= 0 or length > MAX_BODY_BYTES:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid request size")
            return

        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid JSON body")
            return
        if not isinstance(payload, dict) or not isinstance(
            payload.get("messages"), list
        ):
            self._send_error_json(HTTPStatus.BAD_REQUEST, "messages must be a list")
            return

        messages = [
            message for message in payload["messages"] if isinstance(message, dict)
        ]
        model = payload.get("model")
        if not isinstance(model, str) or not model:
            model = DEFAULT_MODEL
        decision = decide(messages, payload.get("tools"))
        if payload.get("stream"):
            self._send_stream(model, decision, messages)
            return
        self._send_json(
            HTTPStatus.OK,
            _completion_payload(model, decision, messages),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="ClinicPilot deterministic model stub")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9000)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), ModelStubHandler)
    server.daemon_threads = True
    sys.stderr.write(f"model stub listening on http://{args.host}:{args.port}\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
