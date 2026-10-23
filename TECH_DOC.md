# ClinicPilot: Technical Design

ClinicPilot combines a conversational interface with ordinary application
services. The configured model (local Gemma by default, with an optional
DeepSeek backup) interprets requests and proposes tool calls. Python code
validates those calls, manages appointment state, and decides what can be saved.

The goal is a small, inspectable clinic demo: answer questions from supplied
records, collect appointment details over several messages, and save a booking
only after confirmation. It supports one patient (`P001`), a shared demo login,
and one backend worker. It is not a clinical decision system or a full scheduling
platform.

For setup commands, see the [README](README.md). For exact request and response
fields, see [API and data contracts](docs/contracts.md).

The [README assessment map](README.md#assignment-coverage) links each assignment
requirement to source code. This document explains the architecture, intent
routing, tool execution, booking state, and database design.

## Architecture

```text
Browser
  | HTTPS through Cloudflare Tunnel
  v
FastAPI application, one Uvicorn worker
  |
  +-- React + TypeScript workbench, built with Vite
  +-- Authentication, conversation API, and streamed chat events
  +-- Agent controller
  |     +-- Local Gemma or optional DeepSeek via the OpenAI Python SDK
  |     +-- Local clinic search: Qwen3 + BM25 + exact matches + Jina reranking
  |     +-- Patient record service
  |     +-- HTTP calls to the application's booking API
  +-- SQLAlchemy services -> SQLite
        sessions, conversations, drafts, bookings, audit events
```

The frontend and backend ship in one Docker image. SQLite lives in a persistent
volume. The embedding model runs in the application on CPU. The local Gemma
endpoint is the primary generation service; DeepSeek is an optional manual
backup. There is no separate model server or vector database inside this image.

### Why These Choices

| Choice | Reason | Trade-off |
| --- | --- | --- |
| FastAPI + Pydantic | Typed HTTP requests and validation at the API boundary | Business rules still need explicit service code |
| SQLite + SQLAlchemy 2 + Alembic | Persistent state and migrations without another service | One worker; no horizontal scaling with the current locks |
| Direct tool loop using the OpenAI SDK | Keeps the model, tool definitions, and execution rules easy to inspect | Retry, history, and recovery logic are maintained in this app |
| FastEmbed/ONNX with Qwen3 and Jina | Local CPU embedding and reranking without another paid API | Models add download size, memory use, and startup work |
| Hybrid search in memory | Handles names and IDs as well as loosely worded questions | Appropriate for the small catalog, not a demonstrated large-scale search system |
| Booking calls through HTTP | Makes the booking API enforce authorization and duplicate prevention | Adds a local HTTP hop inside the same application |
| Server-checked confirmation | Ties permission to an exact saved draft, without another model classification call | Only a defined set of affirmative replies is accepted |
| One image, runtime configuration | Promotes the tested artifact without rebuilding for each environment | Deployment must supply credentials, routes, and persistent storage |

### Runtime Route Boundary

The browser-facing routes are mounted below `DEMO_PATH_PREFIX` (`/demo/` in
development). The implementation also exposes a non-streamed `POST /api/chat`
for the assignment contract; the React workbench uses `POST /api/chat/stream`
to show tool progress and draft updates. Both paths execute the same controller,
conversation ownership checks, patient enforcement, and replay rules.

`GET /api/bookings` is available to an authenticated browser session for the
workbench. `POST /api/bookings` is restricted to the internal tool key and accepts
only `{draft_id, draft_version}` plus the idempotency header. This prevents the
model or browser from choosing a patient, bypassing draft validation, or claiming
success without a saved database record.

The chat body requires `message` and a client-generated `message_id`.
`conversation_id` is omitted or null for a new chat and reused for later turns.
`patient_id` defaults to `P001`; other patient IDs are rejected. Booking creation
returns `201` for a new record and `200` for an idempotent replay.

## Intent Recognition and Routing

Intent recognition uses the configured model's function selection within a custom agent
loop. There is no separate classifier or agent-framework dependency. The system
prompt supplies the current date, P001's context, the saved draft, and tool rules.
The model can combine several tools in a turn or ask a follow-up question.

| User intent | Tool or application path | Result |
| --- | --- | --- |
| Clinic Q&A or treatment/doctor recommendation | `search_knowledge` | Retrieved catalog evidence for a sourced answer |
| Personal medical/allergy history | Injected context or `get_patient_record` | P001's profile and treatment history |
| Existing appointment query | `get_patient_bookings` → `GET /api/bookings` | Current persisted bookings, evaluated against the current date |
| New booking or changed details | `update_booking_draft` | Validated draft, missing fields, or confirmation summary |
| Approval of a complete summary | Server confirmation check → booking REST adapter | Persisted booking and structured success event |

The controller validates every proposed tool name and argument. Confirmation is
an application-owned transition: after authorization, the controller calls the
booking API even if the confirmation model call fails or does not request the
write. This keeps execution tied to the user's approval and saved draft.

## A Chat Request, End to End

1. **Route and authenticate.** The application checks the configured URL prefix
   and session cookie. API calls require a valid session; a conversation must
   belong to that session. The patient is fixed to P001.
2. **Identify the turn.** The client supplies a message ID. Reusing it with the
   same request returns the saved result; changing its content is a conflict.
   Turns within a conversation run in order.
3. **Load context.** The controller reads saved messages, patient context, and
   the current booking draft. It checks whether this message confirms a summary
   presented on the preceding assistant turn.
4. **Call the model and tools.** The selected provider returns text or requests a tool. The
   controller checks the tool name and arguments, executes permitted actions,
   and sends the result back to the model when another round is needed.
5. **Save and display the result.** The application stores the final response,
   source references, draft, and booking events. The UI uses those structured
   results to update its transcript and booking list.

The default limits are six tool rounds, 40 history messages, and a
4,000-character user message. The local provider uses a 120-second timeout,
temperature 0.2, top-p 0.95, top-k 64, and a 2,048-token output cap. The optional
DeepSeek backup uses a 45-second timeout, temperature 0, thinking disabled, and a
1,024-token cap. History trimming preserves tool calls with their results. These
settings do not make live-model behavior deterministic.

### Streaming and Reconnection

The workbench sends chat requests to `POST /api/chat/stream`. Server-Sent Events
(SSE) carry text, tool progress, sources, draft updates, and the final response.
`POST /api/chat` provides a non-streamed response under the same ownership and
retry rules.

A browser disconnect detaches from the run; it does not cancel the work. The
browser can reconnect to `GET /api/chat/runs/{turn_id}` and replay events. Stop
requests use a separate endpoint and ask the run to cancel cooperatively. Runs
execute in the application process, not a durable task queue; process-restart
recovery uses saved turn and booking state instead.

## Search and Patient Context

### Clinic Knowledge

The supplied catalog contains two clinics, four doctors, and five treatments.
Each row becomes one search document: **11 documents in total**. Documents retain
the source filename and record ID; doctor documents also include clinic context.
The index reads from SQLite at runtime and can read the CSVs directly in tests.

Search combines three methods:

- **Exact matching** for IDs, names, and supported name variants.
- **BM25 keyword ranking** over text and metadata, with weights for fields.
- **Semantic similarity** using normalized `Qwen/Qwen3-Embedding-0.6B` vectors
  through FastEmbed/ONNX and NumPy cosine comparisons.

The results are combined using reciprocal rank fusion: a document earns a score
from its position in each result list. This avoids treating a keyword score and
an embedding score as if they used the same scale. Results include the source,
an excerpt, and which search methods found the record.

The configured `jinaai/jina-reranker-v1-turbo-en` reranks the fused candidates,
with exact matches kept first. If reranking fails, search falls back to the fused
ranking. Both models run on CPU; `RERANKER_ENABLED` can disable reranking.

Model revisions are pinned in [model_config.py](backend/app/model_config.py) and
[.env.example](.env.example). Document vectors are cached by model, revision,
and document inputs. The index loads before readiness is reported. Docker
downloads both models during the build and uses cached assets at runtime.

Source references such as `[doc:C001]` connect an answer to a record that the UI
can display. They make answers inspectable; a citation alone does not guarantee
that every generated statement is correct.

### Patient Records

Patient data is not part of the clinic search index. A separate database read
supplies P001's profile and treatment history to the prompt. The
`get_patient_record` tool can read that context again, including recorded
measurements and visit notes. Current bookings come from the booking REST API,
not from model memory or old treatment history.

This separation keeps general catalog search distinct from patient-specific
data. Patient context and retrieved text are sent to the selected provider to
generate answers: local Gemma by default, or DeepSeek when the backup is
explicitly selected.

## Tools and Application Rules

The tool surface contains eight tools, defined in
[`schemas.py`](backend/app/agent/schemas.py):

| Tool | Purpose |
| --- | --- |
| `search_knowledge` | Search clinic, doctor, and treatment records |
| `get_patient_record` | Read P001's profile and treatment history |
| `get_patient_bookings` | Read current bookings through the REST API |
| `update_booking_draft` | Collect or change details; optionally start an edit of an existing booking |
| `abandon_booking_draft` | Discard the current draft |
| `create_booking` | Submit the server-authorized draft; takes no model arguments |
| `delete_patient_booking` | Propose removal of a booking, subject to confirmation |
| `request_demo_reset` | Propose restoring the shared demo, subject to confirmation |

The application validates arguments locally rather than relying on the provider
to enforce the JSON schemas. The model cannot choose the patient, internal URL,
credential, request key, or booking outcome. A request to write is refused unless
the required application state allows it.

## Booking Lifecycle

```text
collecting_details -> awaiting_confirmation -> booking_in_progress -> booked
        ^                     |
        +--- changed details -+

An unfinished draft can also be cancelled.
```

### Collect and Validate

A draft stores the doctor, treatment, local date and time, clinic timezone,
resolved UTC timestamp, optional notes, and a version number. The service checks
IDs, doctor-treatment compatibility, and the requested time. Incomplete drafts
return missing fields and, where applicable, deterministic slot suggestions.
Suggestions are convenience options, not verified availability.

Changing details increments the draft version and clears the previous
confirmation. Changing the doctor also re-resolves the clinic and timezone.
Patient-reported symptoms can be retained in draft notes as
`Patient reports: <exact words>` without adding a diagnosis or inferred severity.

### Present and Confirm

The confirmation summary is built from the saved draft. The application records
which draft version the assistant presented. A write is authorized only if the
draft is complete, that exact version was presented on the preceding assistant
turn, and the new message is a recognized affirmative.

Accepted replies include `yes`, `yes please`, `confirm`, `confirmed`, `go ahead`,
`book it`, `yes book it`, `yes confirm`, and `please book it`. Matching ignores
case, repeated spaces, and trailing sentence punctuation. A reply with a
correction or an extra instruction is not confirmation. An interruption requires
the summary to be presented again before a later affirmative can authorize it.

### Save Once and Recover

The create request contains only the draft ID and version. The internal API
loads the saved details itself and requires both a server credential and
`Idempotency-Key: booking:<draft-id>:v<version>`.

- The same key and details return the existing booking instead of inserting one.
- The same key with different details returns `409 Conflict`.
- The booking write and draft update happen in one database transaction.
- No database transaction stays open while waiting for the model.

The agent retries a lost create response once with the same key. If the booking
was committed but the response is still unavailable, the controller can recover
the result from the saved draft and booking. It also replaces unsupported
generated success wording: the final success message must come from a persisted
booking, even if the model fails after the write.

On application startup, recovery checks turns left in progress by the previous
process. A committed booking can complete its saved response; otherwise the turn
becomes retryable and booking authorization is cleared. This handles a narrow
set of interrupted-turn cases, not general distributed job recovery.

### Edit, Remove, and Reset

An edit starts a draft from an existing booking and updates that row only after
fresh confirmation. Removal marks a booking as deleted so it disappears from the
active list while its record remains. Chat removal requests require a separate
affirmative turn; the workbench also provides an explicit delete control.

Reset is intentionally shared: it restores P001's seed bookings, removes new
P001 bookings, and clears conversations and drafts across sessions. It keeps the
audit events. It is a demo convenience, not a patient-data retention policy.

## Data and Time

SQLAlchemy models and Alembic migrations define these groups of tables:

| Group | Stored data |
| --- | --- |
| `clinics`, `doctors`, `treatments` | Catalog records; each doctor references a clinic |
| `patients`, `patient_treatment_history` | Profiles and history; visits reference a patient and doctor |
| `patient_bookings` | Patient, doctor, treatment foreign keys; local/UTC slot, status, notes, unique idempotency key, and deletion markers |
| `demo_sessions` | Hashed session tokens, expiry, and revocation |
| `conversations`, `chat_turns` | Session ownership, model messages, request hashes, status, and saved responses |
| `booking_drafts` | Conversation-linked versioned details, confirmation markers, authorization, and booking reference |
| `agent_events` | Model calls, tool calls, actions, usage, latency, and payloads |

Prices use integer cents and source IDs are preserved. CSV seeding updates rows
by source ID without overwriting user-created bookings. Bookings include a unique
request key and a hash of their canonical details. Turns have a unique
`(conversation_id, client_message_id)` pair to support safe request replay.
Audit events remain when conversations are deleted or the demo is reset.

Appointments use the selected clinic's local time: C001 is `America/New_York`;
C002 is `America/Los_Angeles`. Python `zoneinfo` resolves local times to UTC.
Past times and ambiguous or nonexistent daylight-saving times are rejected for
clarification. Summaries and the UI display the resolved local time and zone.

The CSVs do not specify which treatments each doctor offers. The explicit mapping
in [`doctor_treatments.json`](backend/app/config/doctor_treatments.json) fills that
gap. Valid future times are otherwise assumed available: there is no calendar
integration, conflict detection, or enforcement of opening hours as availability.

## Frontend and Access

React and TypeScript provide the workbench; Vite builds it with relative asset
URLs. FastAPI injects the runtime path configuration when serving the page.
The production prefix is not compiled into JavaScript or baked into the image.
The UI uses a pinned copy of the Triage design system.

The Assistant view restores saved conversations, displays tool and source
details, and attaches draft and confirmation controls to the relevant turn.
Booking events trigger a fresh read of the booking list. Markdown supports
tables but never renders raw model HTML. The Explorer reads session-scoped
execution traces, including model IDs, latency, tokens, and cost estimates.
Cost rates are configurable and may become outdated; setting them to zero hides
the dollar estimate. They are not provider billing data.

Access is deliberately simple but enforced on the server:

- All browser routes sit under `DEMO_PATH_PREFIX`. Other paths return `404`;
  the prefix without its trailing slash redirects to the canonical path.
- Login checks an Argon2id password hash. Five failed attempts within five
  minutes trigger a per-client throttle. Sessions last eight hours by default.
- Session tokens are random 32-byte values; only their SHA-256 hashes are stored.
  Cookies are `HttpOnly`, `SameSite=Lax`, prefix-scoped, and `Secure` in production.
- Cookie-authenticated writes require a matching origin. Responses include a
  self-only Content Security Policy, no-store caching, and framing protections.
- Booking creation requires the internal key; a browser session alone cannot
  call the create endpoint. Production rejects unsafe placeholder settings and
  the controlled test-model endpoint.
- `/healthz` and `/readyz` accept internal probes with a loopback host and reject
  public-host or Cloudflare-forwarded requests. Readiness checks the database and
  loaded search resources, not the availability of the generation provider.

These controls protect a shared demo. A secret prefix and shared password do not
replace individual accounts, roles, or clinical-system security requirements.

## Testing and Delivery

Tests cover separate questions rather than treating every passing test as
evidence of model quality:

| Check | What it tests |
| --- | --- |
| Backend tests with temporary SQLite and an injected clock | API rules, ownership, drafts, confirmation, retries, recovery, and database effects |
| Frontend tests and build checks | UI logic, TypeScript, lint, and build correctness |
| Playwright against the packaged image and model stub | Browser flows, routing, login, and persistence across restart |
| Local retrieval evaluation | Search results with the real local embedder |
| Separate live DeepSeek evaluation | Recorded end-to-end behavior with the real provider and booking REST API |

Standard tests require no live DeepSeek key or GPU. Live evaluation is opt-in,
makes provider calls, and is not part of pull-request CI. Its results describe
the recorded cases and run, not broad clinical accuracy.

GitHub Actions combines backend, frontend, security, and container/browser checks
in a `quality` gate. Security checks use Gitleaks, `pip-audit`, and `npm audit`.
The multi-stage image uses Node 24 and Python 3.12; runtime uses a non-root user,
CPU ONNX inference, and one Uvicorn worker.

`scripts/ci/changed_domains.py` selects checks by changed inputs. Docs-only
changes run the lightweight classifier and `quality`; unaffected domains are
intentionally skipped. Publication and deployment run only when an image was
built. The model manifest and retrieval modules form a separate cacheable image
stage, with BuildKit layers cached in GitHub Actions (`type=gha`, `mode=max`).
Normal backend edits therefore do not invalidate the model prewarm layer.

After successful `main` CI, the tested image is published to GHCR. A self-hosted
Tailscale runner deploys it by digest over SSH without rebuilding on the VM.
Production Compose publishes no app port; Cloudflare Tunnel supplies HTTPS.
Deployment runs migrations and checks readiness, routing, and authentication.
Failure restores the previous image when available, retaining the database
volume. Migrations must therefore support the previous application version.

The [deployment record](docs/deployment-record.md) documents historical checks,
infrastructure deviations, and the forced-failure rollback drill.

## Current Limits

The demo has no registration, multi-patient accounts, distributed turn queue,
or support for multiple backend workers. Booking edits and removal are local
demo actions, not integration with a clinic scheduling system. The assistant
reads existing medical records but is not designed to diagnose or prescribe.

Saved conversations can outgrow the bounded model context; there is no automatic
transcript summarization. Search covers a small supplied catalog, and model
answers still require evaluation. Persistent bookings, explicit confirmation,
and source inspection make behavior easier to verify; they do not make the
system a production healthcare product.

The optional speech transcript-to-medical-JSON summarizer is not implemented.
Observability is provided by persisted application traces and Explorer rather
than a Langfuse integration.
