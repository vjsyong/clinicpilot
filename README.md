# ClinicPilot

A clinic assistant that answers questions from supplied records and helps a
patient book an appointment through chat. Built with **FastAPI, React, SQLite,
a local Gemma model with an optional manual DeepSeek backup, and local RAG**.

The main design choice is simple: **the model handles the conversation; the
application controls what gets saved.** Booking details, confirmation, duplicate
prevention, and success messages are checked in code rather than left to the
model's judgment.

This is a working demo for one patient, `P001`, using the six CSVs in
[`dkl_ai_interview_data/`](dkl_ai_interview_data/). It is not a clinical system.
Chats and drafts belong to each signed-in browser session. Appointments are
shared because every session represents the same patient.

## Assignment Coverage

This table maps the take-home requirements to the implementation and the
evidence an assessor can inspect.

| Assignment requirement | Implementation | Where to inspect |
| --- | --- | --- |
| Clinic, doctor, and treatment RAG | Hybrid retrieval using exact matches, BM25, embeddings, and reranking | `backend/app/retrieval/`, `backend/app/agent/controller.py` |
| Patient context for the single-patient demo | Server-fixed patient `P001`; profile and treatment history are loaded separately from clinic knowledge | `backend/app/contracts.py`, `backend/app/retrieval/patient_context.py` |
| Intent analysis and multi-turn conversation | Local-model tool-calling controller (optional DeepSeek backup) with persisted conversation and booking-draft state | `backend/app/agent/controller.py`, `backend/app/services/conversations.py` |
| Existing booking lookup | Agent tool calls the internal booking REST API | `backend/app/agent/tools.py`, `backend/app/api/bookings.py` |
| Missing booking parameters | Versioned draft collects doctor, treatment, local date/time, and optional notes | `backend/app/services/drafts.py`, `backend/app/agent/controller.py` |
| Booking persistence | Internal `POST /api/bookings` validates and saves the authorized draft to SQLite | `backend/app/api/bookings.py`, `backend/app/services/bookings.py` |
| Required chat API | Authenticated `POST /api/chat`, plus the streamed `POST /api/chat/stream` used by the UI | `backend/app/api/chat.py`, `backend/app/api/chat_stream.py` |
| Booking list API | Authenticated `GET /api/bookings`, refreshed after booking events | `backend/app/api/bookings.py`, `frontend/src/App.tsx` |
| React demonstration UI | Chat panel, booking draft/confirmation controls, source inspection, and live bookings table | `frontend/src/` |
| Relational database and CSV seed | SQLite schema, Alembic migrations, repeatable seed of all six CSV files | `backend/app/db/models.py`, `backend/app/db/seed.py` |
| Validation and error handling | Pydantic request models, service validation, and structured API errors | `backend/app/contracts.py`, `backend/app/api/errors.py` |
| Technical documentation | Architecture, tool boundary, state machine, schema, recovery, and limitations | [`TECH_DOC.md`](TECH_DOC.md) |

All browser/API URLs are served below `DEMO_PATH_PREFIX`; the examples below
use the local development prefix `/demo/`.

## Assessor Demo

Start the application using [Run Locally](#run-locally), open
<http://127.0.0.1:8000/demo/>, and sign in with `clinicpilot-demo`.

| Step | Prompt or action | What to verify |
| --- | --- | --- |
| 1. Clinic information | `What is the clinic's cancellation policy?` | The answer cites a source record; open the citation to inspect it. |
| 2. Recommendation | `What treatments and doctors are available for knee pain?` | Recommendations refer to services and doctors in the supplied catalog. |
| 3. Patient context | `What allergies are recorded for me?` | The answer uses P001's records without asking for a patient ID. |
| 4. Existing bookings | `When is my next appointment?` | The tool trace shows a booking lookup. If no future booking exists, the answer should say so; seed dates are fixed. |
| 5. Collect details | `Book a Joint & Pain Consultation with Dr. James Wilson.` | The assistant requests missing date/time details and displays a draft. |
| 6. Complete the draft | Provide a **future** date in `YYYY-MM-DD` format and time `15:00`. | The summary shows the doctor, treatment, clinic-local date, time, and timezone. No booking has been created yet. |
| 7. Confirm | Reply `yes` immediately after the summary. | The response reports a saved booking ID. |
| 8. Verify persistence | Open **Bookings**, then reload the page. | The new booking remains. **Refresh** reads the list from the database. |

Use **Explorer** to inspect model/tool calls, latency, token usage, and estimated
cost. **Reset demo** restores seed bookings and clears chats/drafts for all demo
sessions; audit events remain.

Standard automated tests use injected model responses; packaged browser tests
use a controlled model stub. The live demo needs a reachable local model; a DeepSeek key is an optional backup entered in the UI.

### API Surface

All paths are relative to the configured prefix.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/api/chat` | Non-streamed authenticated chat turn |
| `POST` | `/api/chat/stream` | SSE chat turn used by the React workbench |
| `GET` | `/api/bookings` | List current `P001` bookings |
| `POST` | `/api/bookings` | Internal-key-only booking creation from an authorized draft |
| `GET` | `/api/knowledge/status` | Check retrieval readiness and indexed record count |

Booking creation is intentionally not exposed as a browser-authorized write.
The agent sends only a draft ID and version to the internal endpoint; the server
loads the canonical details, validates them, and applies an idempotency key.

### Optional Features

- **Observability:** persisted model/tool traces, latency, tokens, and cost
  estimates in Explorer; implemented locally rather than through Langfuse.
- **Containerization:** Docker Compose, CI browser tests, and image-based deployment.
- **Additional booking controls:** edit and soft-delete existing bookings.
- **Speech transcript summarizer:** not implemented.

## Stack

| Layer | Technology | Role |
| --- | --- | --- |
| Backend | Python 3.12, FastAPI, Pydantic | HTTP API, request validation, and application rules |
| Data | SQLite, SQLAlchemy 2, Alembic | Patient records, conversations, drafts, bookings, and migrations |
| Language model | Local Gemma through the OpenAI Python SDK; optional DeepSeek backup | Conversation and requests to eight defined tools |
| Search | FastEmbed/ONNX, Qwen3 embeddings, Jina reranker, NumPy, BM25 | CPU semantic, keyword, and exact-name retrieval with reranking |
| Frontend | React, TypeScript, Vite, Triage design system | Chat, booking controls, source inspection, and execution traces |
| Delivery | Docker Compose, GitHub Actions, GHCR | Build, test, publish, and deploy the tested image |
| Access | Cloudflare Tunnel, Tailscale + SSH | Public HTTPS access and private deployment |

There is one application container and one backend worker. The app serves both
the API and the built frontend. It needs no Redis, message broker, vector
database, or agent framework.

See [Technical Design](TECH_DOC.md) for the architecture, intent routing,
retrieval pipeline, booking state machine, and database schema.

## Run Locally

### Docker Compose

You need Docker with Compose and a reachable OpenAI-compatible Gemma endpoint.
The first build downloads the embedding and reranker models; both run locally
on CPU.

```bash
cp .env.example .env
# Point LOCAL_MODEL_BASE_URL at the Gemma endpoint.
docker compose -f compose.yaml -f compose.local.yaml up --build
```

Open <http://127.0.0.1:8000/demo/> and sign in with `clinicpilot-demo`.
The local override binds only to loopback and disables the tunnel. Migrations
and repeatable CSV seeding run automatically on container startup.

### Native Development

You need Python 3.12, `uv`, Node.js 24 (used in CI), and a reachable
OpenAI-compatible Gemma endpoint. Run these commands from the repository root:

```bash
cp .env.example .env
# Point LOCAL_MODEL_BASE_URL at the Gemma endpoint.
uv sync --project backend --locked --group dev
uv run --project backend alembic -c backend/alembic.ini upgrade head
(cd backend && uv run python -m app.db.seed)
(cd frontend && npm ci && npm run build)
uv run --project backend uvicorn app.main:app --app-dir backend --port 8000
```

The first native startup downloads the local retrieval models before reporting readiness.
Open the same `/demo/` URL and use the same development password. For frontend
hot reload, run `npm run dev` from `frontend/` in another terminal and open
<http://127.0.0.1:5173/demo/>. Vite proxies API and login requests to the backend.

## Configuration and Data

[`.env.example`](.env.example) lists the settings. The main ones are:

| Setting | Purpose |
| --- | --- |
| `DEFAULT_MODEL` | `local` (default) or `deepseek` |
| `LOCAL_MODEL_BASE_URL`, `LOCAL_MODEL_ID` | Primary OpenAI-compatible Gemma endpoint and model id |
| `LOCAL_MODEL_*` | Local timeout, temperature, top-p/top-k, and output cap |
| `DEEPSEEK_MODEL`, `DEEPSEEK_BASE_URL` | Optional backup endpoint; the key is entered in the UI |
| `DEMO_PATH_PREFIX` | Browser path, `/demo/` locally; supplied at runtime |
| `DEMO_PASSWORD_HASH` | Argon2id hash for the shared login password |
| `INTERNAL_TOOL_KEY` | Credential for server-to-server booking calls |
| `INTERNAL_API_BASE_URL` | Private booking API URL, including the prefix and trailing slash |
| `DATABASE_URL` | SQLite database location |
| `EMBEDDING_MODEL`, `EMBEDDING_REVISION` | Local embedding model and pinned revision |
| `RERANKER_MODEL`, `RERANKER_REVISION`, `RERANKER_ENABLED` | Local reranker and enable/disable setting |
| `MODEL_*_PRICE_PER_MILLION_USD` | Configurable rates for cost estimates, not billing records |
| `CLOUDFLARE_TUNNEL_TOKEN` | Tunnel credential for public deployment |

The chat window has a model picker. The local Gemma model is selected by
default. To use DeepSeek as a backup, choose **Key**, paste the key, and save.
The key is held in process memory only: it is never written to the database or
environment, is never returned to the browser, and is cleared when the app
restarts. If the local server fails, switch the picker to DeepSeek and retry.

Seeding updates source records by ID without overwriting user-created bookings.
Container restarts keep the SQLite database in the named `data` volume. Native
development uses `data/clinicpilot.db` by default.

`docker compose down -v` removes the entire database volume. Keep `.env`,
generated databases, and production credentials out of Git.

## Tests and Evaluation

```bash
# Backend tests: temporary SQLite databases, no live model key or GPU required.
uv run --project backend pytest backend/tests -q

# Frontend tests.
(cd frontend && npm ci && npm test)

# Local gate: lint, formatting, types, tests, frontend build,
# design-system checks, and Compose configuration checks. Requires Docker.
bash scripts/check.sh

# Search evaluation using the real local embedding model.
uv run --project backend python backend/evals/retrieval.py

# Live-model evaluation: requires DEEPSEEK_API_KEY and makes paid API calls.
uv run --project backend python backend/evals/run.py
```

CI also runs dependency and secret scans, then tests the packaged image with
Playwright and a controlled model stub, including persistence after a restart.
Those tests check application behavior; they do not measure live-model answer
quality. Live-model evaluation is separate and is not run in pull-request CI.

Recorded results are in the [evaluation report](docs/evaluation-report.md).
Check its model and revision before applying results to the current configuration.

## Hosted Deployment

Production uses Cloudflare Tunnel, a runtime path prefix, a shared password, and
a reachable local-model endpoint. A DeepSeek key is optional and is entered in
the workbench rather than `.env`. CI publishes the tested image to GHCR; deployment promotes that image by digest
over Tailscale + SSH. A failed deployment restores the previous image while
retaining the database volume.

See [Technical Design](TECH_DOC.md#testing-and-delivery) and the
[deployment record](docs/deployment-record.md) for details and historical checks.
Hosted demo access details are shared privately.

## Scope and Trade-offs

- **One patient, one shared password, one worker.** Session-isolated chats are
  not multi-patient accounts. SQLite and in-process locks suit this demo, not
  multiple application replicas.
- **Shared demo access:** the password protects the hosted demo. It does not
  select the patient; every session uses P001 automatically.
- **Confirmation before creation:** complete booking details are presented for
  explicit approval before the application writes the appointment.
- **No real scheduling integration.** Valid future slots are assumed available.
  Suggested times are not verified openings; operating hours and conflicts are
  not enforced as availability.
- **Explicit dataset assumptions.** Doctor-treatment compatibility is defined in
  [`doctor_treatments.json`](backend/app/config/doctor_treatments.json), because
  the CSVs do not provide it. C001 uses New York time; C002 uses Los Angeles time.
- **No invented services or prices.** The dataset has no allergist or allergy
  service. Consultation fees and treatment prices are separate, not a quoted
  combined total.
- **Records, not medical advice.** The assistant can retrieve existing notes but
  is not designed to diagnose or prescribe. Conversations are stored, with a
  bounded model context rather than automatic transcript summarization.

## Repository Guide

| Path | Contents |
| --- | --- |
| [`backend/app/`](backend/app/) | API, authentication, data services, agent, and retrieval |
| [`backend/tests/`](backend/tests/) | Backend unit and integration tests |
| [`backend/evals/`](backend/evals/) | Retrieval and live-model evaluation |
| [`frontend/`](frontend/) | React workbench and frontend tests |
| [`tests/e2e/`](tests/e2e/) | Browser tests and controlled model stub |
| [`scripts/`](scripts/) | Local checks, deployment, and smoke tests |
| [`vendor/triage/`](vendor/triage/) | Pinned design-system assets and lint tooling |
| [`TECH_DOC.md`](TECH_DOC.md) | Architecture, design decisions, and failure handling |
| [`docs/contracts.md`](docs/contracts.md) | Detailed API and data contracts |
