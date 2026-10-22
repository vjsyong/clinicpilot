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
  and `/readyz`, which are never published through Cloudflare).
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
- Same key + same canonical details returns the original booking.
- Same key + different canonical details returns `409`
  `idempotency_conflict`.
- Booking insertion and idempotency bookkeeping are one transaction; no
  transaction is held during an LLM call.

### Health

- `GET /healthz` liveness: no dependency checks.
- `GET /readyz` readiness: database `SELECT 1` and retrieval resources loaded.
  Does not call DeepSeek.
- Both are reachable only on the internal network (the Cloudflare route only
  publishes the prefix).

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
`idempotency_key UNIQUE`, `request_hash`, `created_at`. Source date/time columns
remain for faithful seeding and display.

`chat_turns` has `UNIQUE(conversation_id, client_message_id)` and stores
`request_hash`, `status`, `response_json`, timestamps.

`booking_drafts` columns: `id`, `conversation_id`, `version`, `status`,
`doctor_id`, `treatment_id`, `local_date`, `local_time`, `timezone`,
`starts_at_utc`, `notes`, `confirmation_message_id`, `authorized_turn_id`,
`booking_id`, timestamps.

`conversations.messages_json` stores the provider conversation including
assistant tool calls and matching tool results. Internal message IDs use the
key `_cp_message_id`; strip unknown keys before sending to the provider.

Seeding is repeatable and never overwrites user-created bookings.

## Agent

Tools exposed to the model (narrow schemas, validated names only):

```text
search_knowledge(query, filters?)
get_patient_bookings()
update_booking_draft(doctor_id?, treatment_id?, local_date?, local_time?, notes?)
abandon_booking_draft()
create_booking()
```

`get_patient_bookings` and `create_booking` perform real HTTP calls to the
internal booking API using `settings.internal_api_base_url` (which includes the
runtime prefix and a trailing slash) and `X-Internal-Tool-Key`. The model never supplies patient identity, destination
URL, credentials, idempotency keys, or success status.

Confirmation rule (conservative, server-side):

- Valid only when a complete draft is `awaiting_confirmation`, the last
  assistant message presented that exact version, and the normalized user text
  is one of: `yes`, `yes please`, `confirm`, `confirmed`, `go ahead`,
  `book it`, `yes book it`, `yes confirm`, `please book it`.
- Case/whitespace/terminal punctuation are normalized. Any correction or extra
  instruction is not a confirmation.
- An interruption clears the presented marker; a fresh summary is required
  before the next confirmation.
- On valid confirmation the server sets `authorized_turn_id`, exposes only
  `create_booking`, executes the REST create, and reports the persisted record.
- If the model fails after the booking is persisted, build the final answer from
  the saved record. Never claim a booking from generated text alone.
- Draft changes increment `version`, validate, clear authorization, and return
  either missing fields or a canonical summary.

## Retrieval

One document per row: 2 clinics, 4 doctors, 5 treatments (11 total). Every
result carries `source_file` and `record_id`. Embeddings are
`sentence-transformers/all-MiniLM-L6-v2` pinned at revision
`1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, normalized, cosine similarity,
in-memory. Cache vectors with an input/model fingerprint. Prewarm before
readiness. Private patient records never enter the shared index.

## Frontend

React + TypeScript + Vite, built to `frontend/dist`. The backend serves
`index.html`, protected assets, and the JSON config element. Required UI:
login, chat transcript, composer, loading state, retry with the same message
ID, source references, booking summary, live bookings table, manual refresh,
new conversation, logout. On `booking_created` refetch bookings. On `401`
return to login. No optimistic booking success, no raw HTML model output, no
duplicate concurrent sends, no secrets in build vars.

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
