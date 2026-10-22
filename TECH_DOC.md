# ClinicPilot — Technical Design

## 1. Scope and constraints

ClinicPilot is a single-patient (P001) clinic assistant built for a time-boxed
MVP. It uses the six supplied CSVs as the only clinic knowledge source and one
shared demo password. The design deliberately avoids a message broker, Redis, a
vector database, a second AI service, streaming, and an agent framework.

The hard invariants are:

- The model proposes; the application validates. The model cannot choose the
  patient, the tool URL, the internal credential, the idempotency key, or
  whether a booking succeeded.
- No booking write without a complete draft, a summary presented on the
  immediately preceding assistant turn, and an unambiguous affirmative.
- A correction bumps the draft version and requires a fresh confirmation.
- Booking create is idempotent on `booking:<draft-id>:v<version>`.
- No database transaction is held open during an LLM call.
- All browser routes live beneath `DEMO_PATH_PREFIX`; wrong-prefix requests are
  `404`, never a redirect to the application.
- Production fails closed on missing or placeholder credentials.

## 2. Components

```text
backend/app/
  main.py          prefix ASGI wrapper, lifespan wiring, readiness resources
  settings.py      runtime configuration, prefix normalization, fail-closed checks
  contracts.py     frozen Pydantic models and service protocols
  api/             chat, bookings, health, page/asset serving, errors, deps
  auth/            Argon2id password, opaque sessions, CSRF/security middleware
  db/              SQLAlchemy models, session factory, repeatable CSV seeding
  services/        conversations/turns, drafts, bookings, catalog/time logic
  agent/           DeepSeek client, tool schemas, REST adapter, controller, prompt
  retrieval/       CSV/DB documents, MiniLM embeddings, cosine index, P001 context
frontend/src/      React workbench (chat + live bookings table)
vendor/triage/     pinned MIT design system and strict lint tooling
```

### Request flow

1. `PrefixApp` accepts only paths beginning with the configured prefix, strips
   the prefix, and forwards to the FastAPI app. `/prefix` is canonicalized to
   `/prefix/` with a `308`. Internal `/healthz` and `/readyz` additionally
   require a loopback `Host`; a public hostname receives JSON `404`.
2. Browser requests use the `clinicpilot_session` cookie. Session tokens are
   random 32-byte values; only their SHA-256 hashes are stored. Cookies are
   `HttpOnly`, `SameSite=Lax`, and `Secure` in production, scoped to the prefix
   path.
3. The `chat` route verifies session ownership, enforces P001, deduplicates the
   client message ID, and serializes turns per conversation.
4. The controller loads stored provider messages and the current draft, decides
   whether the turn is a valid confirmation, and runs a bounded tool loop.
5. After the turn, the route stores the complete `ChatResponse` against the
   `chat_turns` row. A lost HTTP response can be retried with the same message
   ID and returns the stored response without repeating side effects.

### Authentication and browser protections

- `POST /login` takes a shared password, verifies an Argon2id hash, applies a
  per-client 5-failures/5-minutes throttle, and sets an 8-hour session.
- `POST /logout` revokes the session server-side and clears the cookie.
- Unauthenticated page requests redirect to `./login`; unauthenticated API
  requests return JSON `401`.
- Unsafe methods carrying a session cookie are checked against `Origin` (and
  `X-Forwarded-Proto` behind the tunnel). A cookie-authenticated write without a
  matching origin is rejected with `403`.
- Responses carry `Cache-Control: no-store`, `Referrer-Policy: no-referrer`,
  `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, and a self-only
  CSP.

## 3. Data model

Seed tables: `clinics`, `doctors`, `treatments`, `patients`,
`patient_treatment_history`, `patient_bookings`. Prices/fees are stored as
integer cents. Source IDs are preserved.

Additional tables:

- `demo_sessions` — opaque token hash, timestamps, revocation.
- `conversations` — owning demo session, patient, `messages_json`, timestamps.
- `chat_turns` — unique `(conversation_id, client_message_id)`, canonical request
  hash, status, stored response.
- `booking_drafts` — version, status, optional slot fields, canonical
  `starts_at_utc`, timezone, presentation marker, authorization turn, booking id.

`patient_bookings` is extended with `starts_at_utc`, `timezone`,
`idempotency_key UNIQUE`, `request_hash`, and `created_at`. `request_hash` covers
the canonical booking payload (patient, doctor, treatment, resolved slot,
timezone, notes), not just the draft ID/version. Seeded bookings get the clinic
timezone and a normalized UTC timestamp. New IDs are allocated from the next
numeric `B` value inside the insert transaction.

Seeding upserts source rows by source ID and never deletes user-created
bookings, so it is safe to run on every container start.

## 4. Booking state machine

```text
no draft
  → collecting_details        (missing doctor/treatment/date/time)
  → awaiting_confirmation     (complete, canonical summary presented)
  → booking_in_progress       (authorized for this turn)
  → booked

collecting_details / awaiting_confirmation → cancelled
changed details → validate → collecting_details or awaiting_confirmation
external failure → draft retained; authorized turn cleared; retry safely
```

Every meaningful slot change validates the value, re-resolves the clinic
timezone if the doctor changes, increments the version, clears the confirmation
marker, and returns the missing fields or a canonical summary. Summaries are
rendered from the persisted draft, never from regenerated model text.

### Confirmation rule

A confirmation is accepted only when all of the following hold:

1. the draft is complete and `awaiting_confirmation`;
2. the last assistant message presented that exact `(draft_id, version)`;
3. the normalized user text is exactly one of `yes`, `yes please`, `confirm`,
   `confirmed`, `go ahead`, `book it`, `yes book it`, `yes confirm`,
   `please book it`.

Case, surrounding whitespace, repeated spaces, and trailing `.`/`!`/`?` are
normalized. Anything with a correction or extra instruction is not a
confirmation. An interruption clears the presentation marker; a fresh summary is
required before another confirmation can succeed. The controller also replaces
generated prose that claims a booking succeeded when no write was persisted, and
re-presents the canonical summary in that case.

### Idempotency and recovery

`POST /api/bookings` requires `X-Internal-Tool-Key` and
`Idempotency-Key: booking:<draft-id>:v<version>`. The server loads canonical
details from the draft. A replay with the same key and canonical details returns
the existing booking with `200`; the same key with different canonical details
returns `409`. Insert and draft-booked updates happen in one transaction.

The agent retries a lost create response once with the same key. If the response
is still unavailable but the draft is marked booked, the controller reconstructs
the success result from persisted draft/booking data instead of claiming failure.
At startup, `app.services.recovery` releases orphaned in-progress turns and, for
a committed booking, stores the original replay response before traffic resumes.
A failed turn can therefore be retried with the same message ID without a
duplicate write.

## 5. Agent and tools

Six tools are exposed with strict JSON schemas:

```text
search_knowledge(query, filters?)
get_patient_bookings()
update_booking_draft(booking_id?, doctor_id?, treatment_id?, local_date?, local_time?, notes?)
delete_patient_booking(booking_id)
abandon_booking_draft()
create_booking()
```

`get_patient_bookings` and `create_booking` are real HTTP calls to the
application's internal booking API with a server-owned key, base URL (including
the runtime prefix), patient, and idempotency key. They do not open the database.
`create_booking` takes no model arguments. Outside an authorized confirmation
turn it is refused.

The controller bounds the loop (`MAX_TOOL_ROUNDS`, default 6), the context
(`MAX_HISTORY_MESSAGES`, default 40), the provider timeout, and the retry count.
Tool names and arguments are validated before execution. Trimming preserves
assistant tool-call / tool-result pairing. The DeepSeek client uses
`deepseek-flash` by default, non-thinking mode, temperature 0, and strips
internal `_cp_*` message keys before sending.

Booking UX is state-aware. An incomplete draft returns `next_step=choose_slot`
with deterministic clinic-local suggestions; confirmation language is withheld
until a complete summary is presented. The draft card exposes Confirm booking,
and the server accepts the same explicit confirmation. `booking_id` starts an
edit draft that updates the existing row on confirmation. Deletion is a
tombstone: `delete_patient_booking` only proposes it, and a separate affirmative
turn executes it. Patient-reported symptoms are stored in empty draft notes as
`Patient reports: <exact words>` without diagnosis or inferred severity.

Model calls, tool calls, and actions are written to `agent_events` with model
IDs, usage (including cached/reasoning tokens), latency, request context, and
results. The Explorer API is scoped to the authenticated demo session. Costs are
estimates from optional `MODEL_*_PRICE_PER_MILLION_USD` settings; with rates at
zero the UI shows tokens but no dollar estimate.

If the model or provider fails after a confirmed write, the final answer is
built from the persisted booking record. Generated success wording is replaced by
canonical text; when no booking exists it becomes the deterministic
`No booking was created` response. The phrase "booked" is never accepted from
generated text alone. One worker serializes turns per conversation. At startup,
`services/recovery.py` releases turns orphaned by a previous process: a turn
with a committed booking is completed from the persisted record, otherwise it
is failed and its authorized draft returns to confirmation so the same message
ID can be retried.

## 6. Retrieval

One document is built per knowledge row (2 clinics + 4 doctors + 5 treatments =
11). Each has `document_id`, `source_file`, `record_id`, text, and metadata.
Doctor documents include clinic context; treatment documents include category.
No clinical claims are invented to improve similarity.

Documents come from the database in production and directly from the CSVs in
tests. Embeddings use `sentence-transformers/all-MiniLM-L6-v2` at the pinned
revision, normalized, in memory. Document vectors are cached by a SHA-256
fingerprint over model, revision, and document inputs. `prewarm()` builds the
index before readiness is reported.

Retrieval is hybrid: exact ID/name/alias matches, a field-weighted BM25 channel
over document text and metadata, and dense cosine similarity are fused with
reciprocal rank fusion. `search_evidence()` returns the document, score,
channels, and an excerpt; the controller passes a `[doc:<record_id>]` citation
to the model. The deterministic retrieval evaluation lives at
`backend/evals/retrieval.py` (`python backend/evals/retrieval.py`). Patient
records are never added to the shared knowledge index. P001's profile,
allergies, and treatment history are injected into the prompt through a separate
DB read; bookings are read through the REST tool.

## 7. Time handling

Clinics map to `America/New_York` (C001) and `America/Los_Angeles` (C002).
`local_date`/`local_time` are combined with the clinic's zone using `zoneinfo`.
Past times and nonexistent/ambiguous DST local times are rejected with a
clarification rather than guessed. Changing the doctor re-resolves the clinic
and timezone. The UI and confirmation summary display the resolved date, time,
and timezone. Otherwise valid slots are assumed available; operating hours are
not enforced as availability.

## 8. Frontend

The React workbench is built to relative asset URLs (`base: './'`) and fetches
`./api/...`; the backend injects the runtime prefix into a JSON
`#clinicpilot-config` element when it serves the authenticated index. No
production prefix or secret is a build argument or build-time variable.

The Assistant tab uses the vendored Triage chat system. It streams turns over
SSE (`POST /api/chat/stream`), persists conversations per authenticated demo
session, restores the active conversation on reload, and re-attaches to an
in-flight run. The transcript renders safe markdown including GFM tables (never
raw HTML), shows one collapsed tool/source disclosure, turns
`[doc:<record_id>]` citations into a source inspector, and attaches the canonical
draft to the presenting turn. Incomplete drafts show selectable clinic-local
slot suggestions; complete drafts show Confirm booking. Booking rows expose
Edit, armed Delete, and the shared Reset demo action. The Explorer tab shows
session-scoped model calls, tools, actions, messages, tokens, and optional cost
estimates. Copy, retry, regenerate, and stop are available; the composer is
docked on phones and the history rail becomes a sheet. Bookings refetch after
booking created/updated/deleted. A failed send retries with the same message ID.
Concurrent duplicate sends are prevented and `401` returns to login. The login
page is server-rendered and uses only public design-system assets; application
assets are served only to authenticated sessions.

## 9. Containers and CI

The multi-stage image builds the frontend with Node 24 and the backend with
Python 3.12, installs CPU-only PyTorch, prewarms the pinned embedding model, and
runs as a non-root user. One Uvicorn worker. SQLite lives in a named data
volume. The production Compose file publishes no application port; `cloudflared`
is an opt-in profile. CI uses a separate Compose project, a deterministic
OpenAI-compatible model stub, ephemeral volumes, no production credentials, and
always cleans up.

CI jobs: backend (ruff, format, mypy, pytest), frontend (lint, typecheck, tests, build,
strict vendored Triage lint), security (Gitleaks, pip-audit, npm audit),
container (image build, Compose smoke, Playwright, restart persistence), and an
aggregate `quality` gate. Every external action is pinned to a full commit SHA.
Publication to GHCR happens only after a successful `main` run, loads the exact
image artifact tested by the container job, tags it with the full commit SHA, and
records the digest. Deployment promotes that digest through Tailscale-only SSH; it
never rebuilds. Rollback restores the previous image but deliberately leaves the
database volume untouched. The deploy job runs on a repository-scoped self-hosted
runner that is a tailnet member and uses a key-only SSH credential over Tailscale
MagicDNS to the dedicated VM. The ephemeral GitHub-hosted + Tailscale OAuth join
was unavailable; this is the documented runner deviation. `main` requires the
aggregate `quality` status. Automatic rollback was exercised with a forced
readiness failure: the previous digest was restored and the database volume
remained. Public deployment probes require health paths to return `404`.

## 10. Evaluation

- Deterministic tests assert facts, source records, valid tool actions, state
  transitions, idempotency, and database effects. They do not assert generated
  prose.
- `backend/evals/run.py` runs representative cases against the real DeepSeek
  model with a temporary SQLite database and the real booking REST API. It is
  not part of PR CI and never prints secrets.
- Live-model results are reported separately from mocked tests. The recorded run
  is the only evidence of live-model quality.

## 11. Decisions and limitations

Decisions:

- SQLite + one worker + per-conversation in-process locks for a small shared
  demo; this avoids distributed coordination while preserving serialized turns.
- Server-side confirmation vocabulary rather than trusting another model
  classification call.
- HTTP booking tools rather than direct repository access, so the model cannot
  bypass the API boundary.
- CSV-derived retrieval documents for tests and DB-derived documents in
  production, with the same document contract.
- A conservative generated-prose guard on top of the structural success event.

Limitations:

- Shared password and single patient; no registration or multi-patient auth.
- No availability/conflict detection, diagnosis, or prescribing. Delete and
  reschedule are explicit demo actions; delete is a tombstone, not hard removal.
- In-process locks and SQLite do not scale horizontally; the MVP is one worker.
- An in-flight turn is marked `in_progress` and a concurrent duplicate receives a
  retryable `409`. Startup recovery releases turns orphaned by a previous
  process, replaying a committed booking response or making the turn retryable
  with the same message ID.
- Automatic deployment depends on external VM, tailnet, Cloudflare, and GHCR
  configuration. It fails closed when those are unavailable and does not claim
  success without direct readiness and public-route evidence.
- Remote GitHub Actions, GHCR publication, digest promotion, branch protection,
  and a forced-failure rollback drill are recorded in
  `docs/deployment-record.md`. The deployment runner is a repository-scoped
  self-hosted tailnet member rather than an ephemeral GitHub-hosted Tailscale
  runner, and the VM runs on `enterprise` because `cerritos` lacks KVM.
- The planned `cerritos` node cannot run QEMU guests (no KVM), so the recovered
  VM runs on `enterprise` with the same CPU/RAM/disk shape.
- The public image contains no production prefix or credentials; the demo URL
  and password are handed over privately, not in this document.
