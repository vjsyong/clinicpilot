# AGENTS.md — ClinicPilot

ClinicPilot is a single-patient (P001) clinic assistant: a FastAPI + SQLite
backend, a local-embedding retrieval layer, a DeepSeek tool-calling agent, and a
React workbench, shipped as one container behind a Cloudflare tunnel.

`docs/contracts.md` is the frozen cross-package contract. `implementation_plans/
clinicpilot-mvp/plan.md` is the execution plan and acceptance matrix. Read the
relevant part before changing behaviour.

## Commands

```bash
# Backend (from repo root)
uv sync --project backend --locked --group dev
uv run --project backend alembic -c backend/alembic.ini upgrade head
uv run --project backend ruff check backend
uv run --project backend ruff format --check backend
uv run --project backend mypy backend/app
uv run --project backend pytest backend/tests -q

# Frontend
cd frontend && npm ci && npm run lint && npm run typecheck && npm run build

# Full local gate (wraps the above plus triage lint and compose checks)
bash scripts/check.sh
```

## Rules that bite

- All browser routes live under `DEMO_PATH_PREFIX`; wrong-prefix requests are
  `404`, never a redirect to the app.
- Never bake the production prefix, password, API key, internal key, or tunnel
  token into the image or Git. Production must fail closed on missing or
  placeholder credentials.
- The model proposes; the application validates. The model cannot choose the
  patient, tool URL, credentials, idempotency key, or booking success.
- No booking write without a complete draft, a just-presented summary, and an
  unambiguous affirmative from the user. Corrections bump the draft version and
  require reconfirmation.
- Booking create is idempotent on `booking:<draft-id>:v<version>`; same key with
  different canonical details is a `409`.
- Do not hold a database transaction open during an LLM call.
- One backend worker. Turns are serialized per conversation.
- No raw HTML rendering of model text. No optimistic booking success.
- The shared demo has one patient (P001); conversations are isolated per
  authenticated browser session.
- Do not hand-edit `vendor/triage/**`; it is a pinned copy with its license.
- Tests use temporary SQLite databases and an injected clock. Standard tests
  must not need a live DeepSeek key or GPU.

## Work packages and ownership

Path ownership is listed in `docs/contracts.md` §Ownership. Parallel workers may
only edit owned paths; shared contract changes go through the integrator. One
writer per path. Commit only when explicitly authorized.
