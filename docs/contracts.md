# ClinicPilot frozen contracts (WP0)

This file is the execution contract for the MVP. It is normative for WP1
(persistence/auth/API), WP2 (agent/retrieval), WP3 (frontend), WP4
(containers/CI), WP6 (integration), and WP7 (deployment). Change a contract
centrally with the integrator; never silently fork one.

## Runtime and prefix

- One application process, one Uvicorn worker.
- Every browser-facing route lives beneath `DEMO_PATH_PREFIX`:
  - development: `/demo/`
  - production: `/<generated-secret>/`
- `/demo` (no slash) redirects `308` to `/demo/`.
- Anything outside the prefix returns `404` JSON (except internal `/healthz`
  and `/readyz`). Health routes are accepted only for a loopback `Host`
  (`127.0.0.1`, `localhost`, `::1`); any public hostname receives the same
  prefix-style JSON `404`.
- Cookies are scoped to the prefix path, `HttpOnly`, `SameSite=Lax`, and
  `Secure` when `APP_ENV=production`.
- The frontend uses relative URLs only (`./api/chat`, `./assets/...`) so the
  runtime prefix is never baked into the image.
- The backend injects this element before `</head>` of `index.html` when it
  serves an authenticated page:
  ```html
  <script id="clinicpilot-config" type="application/json">{"prefix":"/demo/","appName":"ClinicPilot"}</script>
  ```
  The JSON is HTML-safe (`<`, `>`, `&`, U+2028/U+2029 escaped).

## Python module layout and factory names

```text
app.settings.get_settings() -> Settings
app.settings.Settings.validate_runtime()          # fail closed in production
app.clock.SystemClock / FrozenClock
app.contracts                                     # frozen models/protocols
app.db.session.create_session_factory(settings)   # -> (engine, sessionmaker)
app.db.models                                     # SQLAlchemy models (WP1)
app.db.seed.seed_all(session_factory, settings)   # idempotent (WP1)
app.services.bookings.BookingService              # (WP1)
app.services.drafts.DraftService                  # (WP1)
app.services.conversations.ConversationService    # (WP1)
app.auth.sessions.SessionService                  # (WP1)
app.auth.routes.router                            # GET/POST login, POST logout, GET index
app.api.router                                    # includes chat/bookings/health
app.agent.controller.build_controller(settings, session_factory, clock)
app.retrieval.index.build_knowledge_index(settings, session_factory)
```

`main.py` owns lifespan wiring: it creates the engine/session factory, builds
and prewarms the knowledge index, stores `app.state.settings`,
`app.state.session_factory`, `app.state.knowledge_index`, `app.state.clock`, and
`app.state.controller`.

## API

All paths are relative to the prefix.

### `POST /login` and `POST /logout`

- `POST /login` accepts form fields `password` (and optional `next`).
- Success sets the session cookie and redirects `303` to the sanitized
  prefix-relative `next` or the workbench root. Failure re-renders the login
  page with an error and status `401`.
- Login throttling is per client address (5 failures / 5 minutes).
- `GET /login` renders the password page. `POST /logout` revokes the session
  and redirects to `./login`.

### `POST /api/chat`

Request (Pydantic `app.contracts.ChatRequest`):

```json
{"conversation_id": null, "message_id": "uuid", "message": "hello", "patient_id": "P001"}
```

- `message_id` is required (1-200 chars). Message length is capped by
  `settings.max_message_chars` (default 4000).
- `patient_id` may be omitted; any value other than `P001` returns `403`.
- A conversation belonging to another demo session returns `404`.
- Duplicate `(conversation_id, message_id)` with the same canonical request
  hash returns the stored `ChatResponse` (`200`).
- Duplicate message ID with different request content returns `409`
  `message_id_conflict`.
- An actively processing duplicate returns `409` `turn_in_progress` with
  `retryable: true`.
- Turns are serialized per conversation.

Response: `app.contracts.ChatResponse` (assistant text, source refs, canonical
draft view or null, events). A successful booking emits:
`{"type": "booking_created", "booking": {<BookingView>}}`.

### `POST /api/chat/stream`

Same `ChatRequest` body and authentication/ownership/idempotency rules as
`POST /api/chat`, but returns `text/event-stream`. Events, in order as they
occur:

- `session`: `{conversation_id, turn_id, message_id}` (always first)
- `status`: `{stage}` (`thinking`, `confirming`, `booking`, `booked`)
- `content`: `{delta}` for streamed assistant text
- `content_break`: paragraph boundary between tool rounds
- `tool_start`: `{id, name, args}`
- `tool_end`: `{id, name, ok, summary, sources}`
- `sources`: `{sources: [SourceRef]}`
- `draft`: `{draft: BookingDraftView}`
- `next_step`: the state-aware `NextStep` (`choose_slot`, `confirm_booking`,
  `collect_details`, `confirm_action`, or `completed`)
- `done`: the complete `ChatResponse`
- `error`: `{code, message, retryable}`
- `stopped`: the turn was cancelled

Runs execute in the background. A disconnect only detaches the subscriber; the
turn still finishes and persists its `ChatResponse`. `GET /api/chat/runs/
{turn_id}` replays the same events and `POST /api/chat/runs/{turn_id}/stop`
requests cooperative cancellation. Stopping fails the turn so the same message
ID can be retried.

### `POST /api/chat/regenerate`

Body: `{"conversation_id": "...", "message_id": "<last user message id>"}`.
Trims the last assistant reply, starts a fresh turn for the same user text, and
returns the same SSE event stream. Confirmation turns and turns that already
persist a booking are refused with `409`.

### Booking actions

- `DELETE /api/bookings/{booking_id}` hides a P001 booking from the active list
  with a tombstone (`deleted_at`, `deleted_reason`). The row and its audit
  history remain. Browser session or internal key allowed.
- `POST /api/demo/reset` restores the P001 seed bookings (B1001, B1004), removes
  application-created P001 bookings, clears all conversations/drafts, and keeps
  audit events. It is browser-session only and requires CSRF/origin checks.
- `GET /api/audit?limit=300` returns the current demo session's durable trace
  events: model calls, tool calls, and actions, including usage, latency,
  model IDs, and request/response payloads. Other sessions are never included.
  The response also reports configured pricing rates; costs are estimates and
  are unavailable until rates are configured.

### Conversation history

- `GET /api/conversations` lists the authenticated demo session's chats
  (`ConversationSummary`: title, timestamps, counts, active turn).
- `GET /api/conversations/{id}` returns the transcript, per-turn sources,
  booking draft, tool trace, and the current draft.
- `DELETE /api/conversations/{id}` deletes only a conversation owned by the
  authenticated demo session.

### Knowledge inspection

- `GET /api/knowledge/status` reports readiness, record count, and the pinned
  embedding model.
- `GET /api/knowledge/{source_file}/{record_id}` returns one hydrated knowledge
  record for the assistant source inspector. Authenticated sessions only.

### `GET /api/bookings`

Allowed with a browser session or `X-Internal-Tool-Key`. Returns P001 bookings
only, newest/upcoming ordering. Every item is `app.contracts.BookingView`.
"Next appointment" is the earliest future, non-cancelled booking using the
injected clock; completed/historical rows are never presented as upcoming.

### `POST /api/bookings`

Only `X-Internal-Tool-Key` may create. A browser cookie alone returns `401`.
Request: `{"draft_id": "...", "draft_version": 2}`. Header:
`Idempotency-Key: booking:<draft-id>:v<version>`.

- Loads canonical details from the draft; never trusts a second copy.
- `201` new booking, `200` idempotent replay, `409` conflict, `422` invalid.
- The stored request hash is computed from the canonical booking payload
  (patient, doctor, treatment, resolved local/UTC slot, timezone, notes), not
  merely from the draft ID and version.
- Same key + same canonical details returns the original booking.
- Same key + different canonical details returns `409`
  `idempotency_conflict`.
- Booking insertion and idempotency bookkeeping are one transaction; no
  transaction is held during an LLM call.

### Health

- `GET /healthz` liveness: no dependency checks.
- `GET /readyz` readiness: database `SELECT 1` and retrieval resources loaded.
  Does not call DeepSeek.
- Both require a loopback `Host` header. The Cloudflare route publishes only the
  prefix, and any public-host request for a health path returns `404`.

### Error shape

```json
{"error": {"code": "draft_version_conflict", "message": "...", "retryable": false},
 "request_id": "uuid"}
```

Known codes: `unauthorized`, `forbidden`, `not_found`, `message_id_conflict`,
`turn_in_progress`, `draft_incomplete`, `draft_version_conflict`,
`confirmation_required`, `invalid_booking_details`, `idempotency_conflict`,
`provider_error`, `rate_limited`, `internal_error`. Never expose stack traces,
credentials, or raw provider responses.

## Database

Migration-owned SQLite schema with `PRAGMA foreign_keys=ON` on every
connection. Tables:

`clinics`, `doctors`, `treatments`, `patients`, `patient_bookings`,
`patient_treatment_history`, plus `demo_sessions`, `conversations`,
`chat_turns`, `booking_drafts`.

`patient_bookings` is extended with `starts_at_utc`, `timezone`,
`idempotency_key UNIQUE`, `request_hash` (canonical booking-details hash),
`created_at`, `deleted_at`, and `deleted_reason`. Source date/time columns remain
for faithful seeding and display. Deletes are tombstones; active lists exclude
them.

`chat_turns` has `UNIQUE(conversation_id, client_message_id)` and stores
`request_hash`, `status`, `response_json`, timestamps. `response_json` includes
the turn's `NextStep` so saved conversations restore actionable cards.

`booking_drafts` columns: `id`, `conversation_id`, `version`, `status`,
`doctor_id`, `treatment_id`, `local_date`, `local_time`, `timezone`,
`starts_at_utc`, `notes`, `confirmation_message_id`, `confirmation_version`,
`authorized_turn_id`, `booking_id`, timestamps. `BookingDraftView` exposes the
presentation marker and `booking_id` so recovery can verify the exact presented
version without trusting conversation text.

`agent_events` is an append-only trace keyed by `demo_session_id`; it has no
foreign key to conversations so reset/delete preserve the audit. It stores the
event type, name, status, payload JSON, and timestamp.

`conversations.messages_json` stores the provider conversation including
assistant tool calls and matching tool results. Internal message IDs use the
key `_cp_message_id`; strip unknown keys before sending to the provider.

Seeding is repeatable and never overwrites user-created bookings.

## Agent

Tools exposed to the model (narrow schemas, validated names only):

```text
search_knowledge(query, filters?)
get_patient_record()
get_patient_bookings()
update_booking_draft(booking_id?, doctor_id?, treatment_id?, local_date?, local_time?, notes?)
delete_patient_booking(booking_id)
abandon_booking_draft()
request_demo_reset()
create_booking()
```

`get_patient_bookings` and `create_booking` perform real HTTP calls to the
internal booking API using `settings.internal_api_base_url` (which includes the
runtime prefix and a trailing slash) and `X-Internal-Tool-Key`. The model never supplies patient identity, destination
URL, credentials, idempotency keys, or success status. `get_patient_record`
renders P001's server-owned profile and treatment history from the database; it
never accepts a patient parameter and is never added to the shared index.

Confirmation rule (conservative, server-side):

- Valid only when a complete draft is `awaiting_confirmation`, the last
  assistant message presented that exact version, and the normalized user text
  is one of: `yes`, `yes please`, `confirm`, `confirmed`, `go ahead`,
  `book it`, `yes book it`, `yes confirm`, `please book it`.
- Case/whitespace/terminal punctuation are normalized. Any correction or extra
  instruction is not a confirmation.
- An interruption clears the presented marker before the provider call, so a
  provider failure cannot leave the old summary authorized. A fresh summary is
  required before the next confirmation.
- Startup recovery releases orphaned in-progress turns and reconstructs the
  original response from a committed booking before any retry can write again.
- On valid confirmation the server sets `authorized_turn_id`, exposes only
  `create_booking`, executes the REST create, and reports the persisted record.
- If the model fails after the booking is persisted, build the final answer from
  the saved record. Never claim a booking from generated text alone.
- Draft changes increment `version`, validate, clear authorization, and return
  either missing fields or a canonical summary.
- When a draft is missing a date or time, the server appends deterministic
  clinic-local slot suggestions and returns `next_step=choose_slot`; it must not
  ask for confirmation. A draft becomes confirmable only with a complete,
  just-presented canonical summary. The UI's Confirm booking button sends the
  same explicit confirmation accepted by the server.
- `update_booking_draft` with `booking_id` starts an edit draft. Confirmation
  updates that row instead of inserting a new booking. Deletion proposals always
  require a separate confirmation turn; the row is tombstoned and the audit is
  retained.
- Patient-reported symptoms are captured into empty draft notes as
  `Patient reports: <exact words>`; the model never diagnoses or infers severity.

## Retrieval

One document per row: 2 clinics, 4 doctors, 5 treatments (11 total). Every
result carries `source_file` and `record_id`. Embeddings are
`sentence-transformers/all-MiniLM-L6-v2` pinned at revision
`1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, normalized, in-memory. Retrieval
fuses three channels with reciprocal rank fusion: exact ID/name/alias matches, a
field-weighted BM25 channel over text and metadata, and dense cosine similarity.
Evidence results add `score`, `channels`, `excerpt`, and a `[doc:<record_id>]`
citation for the model and UI. Cache vectors with an input/model fingerprint.
Prewarm before readiness. Private patient records never enter the shared index.

## Frontend

React + TypeScript + Vite, built to `frontend/dist`. The backend serves
`index.html`, protected assets, and the JSON config element. The Assistant tab
uses the vendored Triage chat system: a saved-conversation rail (sheet on
phones), streamed turn status, one collapsed tool/source disclosure, safe
markdown (including GFM tables), `[doc:<record_id>]` citations that open a
source inspector, copy, retry, regenerate, stop, a draft card attached to the
presenting turn with slot suggestions and Confirm booking, booking edit/delete
controls, a reset action, and an Agent Explorer tab for the current session.
Required UI also includes login, booking summary, live bookings table, manual
refresh, new conversation, and logout. On `booking_created` refetch bookings.
On `401` return to login. No optimistic booking success, no raw HTML model
output, no duplicate concurrent sends, no secrets in build vars.

## Ownership map

| Path | Owner |
| --- | --- |
| `AGENTS.md`, `CONTRIBUTING.md`, `docs/contracts.md`, `backend/app/main.py`, `settings.py`, `contracts.py`, `clock.py` | WP0/integrator |
| `backend/app/api/`, `auth/`, `db/`, `services/`, `migrations/`, `alembic.ini`, tests `api/ auth/ persistence/` | WP1 |
| `backend/app/agent/`, `retrieval/`, `config/`, tests `agent/ retrieval/`, `backend/evals/` | WP2 |
| `frontend/`, `vendor/triage/` | WP3 |
| `Dockerfile`, `compose*.yaml`, `.dockerignore`, `.github/workflows/ci.yml`, `.github/CODEOWNERS`, `pull_request_template.md`, `scripts/check.sh`, `scripts/smoke_test.py`, `tests/e2e/` | WP4 |
| `README.md`, `TECH_DOC.md` | WP8/integrator |
| `.github/workflows/deploy.yml`, `scripts/deploy.sh` | WP7 |

Login presentation decision: WP1 owns `backend/app/templates/login.html` and the
server-rendered login route. WP3 owns application assets and may style the
login page only through the public design-system stylesheet served at
`/public/triage/base.css` and `/public/triage/tokens.css`; WP3 must not edit the
login template.
