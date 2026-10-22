# ClinicPilot

Public repository: <https://github.com/vjsyong/clinicpilot>

ClinicPilot is a single-patient clinic assistant for the supplied
`dkl_ai_interview_data` dataset. It answers grounded questions about clinics,
doctors, and treatments, collects appointment details over multiple chat turns,
requires an explicit confirmation before writing, persists bookings through a
REST API, and shows the persisted bookings in a React workbench.

The shared demo has one patient (P001). Conversations and booking drafts are
isolated per authenticated browser session; bookings are shared.

## Architecture

```text
Browser ── HTTPS ── Cloudflare Tunnel
                        │
                 ┌──────▼────────┐
                 │ FastAPI + React│  one container, one worker
                 │  /<prefix>/    │
                 └──┬────────┬────┘
                    │        │
              SQLite│        │HTTP (internal key)
                    │        ▼
                    │   /api/bookings
                    ▼
        retrieval (local MiniLM) + DeepSeek tool-calling agent
```

- **Backend:** Python 3.12, FastAPI, Pydantic, SQLAlchemy 2, Alembic, SQLite.
- **Agent:** OpenAI-compatible DeepSeek client with five narrow tools. The model
  proposes; the application validates patient identity, draft versions,
  confirmation, idempotency, and booking success.
- **Retrieval:** `sentence-transformers/all-MiniLM-L6-v2` (pinned revision),
  in-memory hybrid retrieval over one document per clinic/doctor/treatment row:
  exact ID/name matches + BM25 + cosine, fused with reciprocal rank fusion.
- **Frontend:** React + TypeScript + Vite, built to relative URLs so the runtime
  prefix is never baked into the image. The Assistant tab streams turns, keeps
  saved conversations, renders safe markdown (including tables) with
  `[doc:...]` citations, suggests clinic-local appointment slots, exposes a
  Confirm booking card, and preserves patient-reported symptoms in draft notes.
  Booking rows support edit/delete, the demo can be reset, and an Explorer tab
  shows the current session's model calls, tools, actions, tokens, and optional
  cost estimates.
- **Ingress:** Cloudflare Tunnel; the application handles the prefix itself.
  Wrong-prefix requests are `404`.

## Quick start (local, native)

Prerequisites: Python 3.12, `uv`, Node 20+, and network access for the first
model download.

```bash
cp .env.example .env
# Set DEEPSEEK_API_KEY in .env. Development defaults are prefix /demo/ and
# password "clinicpilot-demo".

uv sync --project backend --locked --group dev
uv run --project backend alembic -c backend/alembic.ini upgrade head
(cd backend && uv run python -m app.db.seed)
uv run --project backend uvicorn app.main:app --app-dir backend --port 8000

# second terminal
cd frontend && npm ci && npm run build
```

Open <http://127.0.0.1:8000/demo/> and sign in with `clinicpilot-demo`.

For frontend hot reload, run `npm run dev` in `frontend/` instead of building;
Vite proxies `/demo` to `http://127.0.0.1:8000` and serves at
<http://127.0.0.1:5173/demo/>.

## Quick start (containers)

```bash
cp .env.example .env
# production-like local run: set APP_ENV=development (the default), keep the
# dev prefix/password, and set DEEPSEEK_API_KEY.
docker compose -f compose.yaml -f compose.local.yaml up --build
```

The application is published only on `127.0.0.1:8000`; the tunnel service is
disabled in the local override. Health endpoints (`/healthz`, `/readyz`) are
accepted only from a loopback host and are not published through the tunnel.

The production topology (`compose.yaml`) publishes no application port and runs
`app` plus `cloudflared`:

```bash
docker compose --profile tunnel up -d --build
```

Production requires `APP_ENV=production`, a generated
`DEMO_PATH_PREFIX=/<secret>/`, an Argon2id `DEMO_PASSWORD_HASH`, a 32+ character
`INTERNAL_TOOL_KEY`, `DEEPSEEK_API_KEY`, and `CLOUDFLARE_TUNNEL_TOKEN`. The
application refuses to start with missing or placeholder values.

Generate a password hash:

```bash
(cd backend && uv run python -m app.auth.password)
```

## Configuration

| Name | Purpose |
| --- | --- |
| `APP_ENV` | `development`, `test`, or `production` |
| `DEMO_PATH_PREFIX` | Runtime browser prefix, e.g. `/demo/` or `/<secret>/` |
| `DEMO_PASSWORD_HASH` | Argon2id hash of the shared demo password |
| `INTERNAL_TOOL_KEY` | Server-to-server booking API credential |
| `INTERNAL_API_BASE_URL` | Internal base URL including the prefix, trailing slash |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_MODEL` / `DEEPSEEK_BASE_URL` | Generation |
| `DATABASE_URL` | SQLite URL (`sqlite:////app/data/clinicpilot.db` in Docker) |
| `EMBEDDING_MODEL` / `EMBEDDING_REVISION` | Pinned local embedding model |
| `CLOUDFLARE_TUNNEL_TOKEN` | Production tunnel connector token |

Never commit `.env`, the prefix, the password, API keys, the internal key, the
tunnel token, or generated patient databases. Production credentials are
runtime configuration only.

## Database initialization and reset

Normal startup is non-destructive:

```bash
uv run --project backend alembic -c backend/alembic.ini upgrade head
(cd backend && uv run python -m app.db.seed)   # idempotent
```

`seed_all` upserts the six source datasets by their source IDs and never deletes
or overwrites user-created bookings. Running it twice is safe.

A **destructive reset** deletes all data, including demo bookings:

```bash
# native
rm -f data/clinicpilot.db
uv run --project backend alembic -c backend/alembic.ini upgrade head
(cd backend && uv run python -m app.db.seed)

# containers (removes the named volume)
docker compose down -v
```

Restarting or recreating the application container without `-v` keeps the
`data` volume and therefore keeps bookings.

## Model download

The embedding model is downloaded once at image build time into `/opt/hf`
(Docker) or into the Hugging Face cache (native). The revision is pinned:
`1110a243fdf4706b3f48f1d95db1a4f5529b4d41`. The application prewarms the model
before reporting readiness. Set `HF_HOME` to reuse a cache offline.

## Tests

```bash
# Backend unit/integration tests (temporary SQLite, injected clock; no API key)
uv run --project backend pytest backend/tests -q

# Lint, format, types
uv run --project backend ruff check backend
uv run --project backend ruff format --check backend
uv run --project backend mypy backend/app

# Frontend
cd frontend && npm ci && npm run lint && npm run typecheck && npm run build

# Design-system gate (vendored tooling, same strict rules as public CI)
python3 vendor/triage/lint/triage_lint.py . --strict

# Full local gate
bash scripts/check.sh
```

Browser acceptance runs against the packaged image plus a deterministic
OpenAI-compatible model stub:

```bash
docker compose -p ci-clinicpilot-local -f compose.yaml -f compose.ci.yaml \
  up -d --build --wait app model-stub
CLINICPILOT_E2E_BASE_URL=http://127.0.0.1:8000 \
CLINICPILOT_E2E_PREFIX=/ci-clinicpilot-0123456789/ \
CLINICPILOT_E2E_PASSWORD=clinicpilot-ci-password \
E2E_STATE_FILE=/tmp/clinicpilot-e2e/state.json npm run test:e2e:functional
```

Retrieval evaluation (local embedder, no API key):

```bash
uv run --project backend python backend/evals/retrieval.py
```

Live-model evaluation (requires a DeepSeek key; never run in PR CI):

```bash
DEEPSEEK_API_KEY=... uv run --project backend python backend/evals/run.py
```

## CI and deployment

`.github/workflows/ci.yml` runs backend, frontend, security, container/browser,
and aggregate `quality` jobs on pull requests and pushes to `main`. Container CI
builds the production image, starts it with the model stub, runs Playwright,
restarts the app to prove persistence, saves the exact tested image, and cleans
up its isolated Compose project. Publication to GHCR happens only for a
successful `main` CI run and does not rebuild the image.

`.github/workflows/deploy.yml` promotes that tested image by digest to the
dedicated VM. It verifies the workflow event, repository, branch, CI conclusion,
published digest, and deployed revision before touching the host. The deploy job runs on a repository-scoped self-hosted runner that is a member
of the tailnet and connects to the VM over Tailscale MagicDNS (`DEPLOY_HOST`)
with a key-only SSH credential. This avoids a public SSH ingress; the runner is
scoped to this repository and receives the deploy key only in the protected
`production` environment. The ephemeral GitHub-hosted + Tailscale OAuth join
from the plan was unavailable, so this is the documented runner deviation. `scripts/deploy.sh` runs backward-compatible
migrations as a separate step, updates only the application container, checks
private readiness plus non-mutating public routing/auth probes, and restores the
previous image if health fails. A rollback never deletes or restores the SQLite
volume; on the first deployment there is no previous image to restore.

Deployment credentials are environment secrets (`DEPLOY_SSH_KEY`,
`DEPLOY_HOST_KEY`) and repository variables (`DEPLOY_HOST`, `DEPLOY_USER`,
`DEPLOY_PATH`). They are never available to pull-request CI.

### Deployment status for this build

The application is deployed on a dedicated VM (`clinicpilot-demo`, VM 106) on
`enterprise` behind a Cloudflare tunnel, with the runtime prefix and password
kept out of this repository. Public login, grounded Q&A, the draft →
confirmation → booking flow, and restart persistence were verified against that
deployment. See `docs/deployment-record.md` for non-secret operational details.

The full promotion path was exercised on the public repository:

- CI run `39757644785` passed backend, frontend, security, container/browser,
  `quality`, and publication.
- Deploy run `39758580196` promoted the exact published digest
  `sha256:8cefd033...` for commit `8d7a19f`; a rerun correctly skipped because
  that SHA was already deployed.
- Branch protection on `main` requires the aggregate `quality` status.

The image is public on GHCR, so the VM pulls the digest without a registry
credential. Automatic rollback was exercised with a forced readiness failure: the
previous digest was restored and the database volume (including B1005) remained.

## Dataset assumptions

- `D101→[T001,T004]`, `D102→[T002]`, `D103→[T003]`, `D104→[T005]`. The supplied
  CSVs do not define doctor–treatment compatibility, so this explicit
  application assumption is stored in `backend/app/config/doctor_treatments.json`.
- C001 uses `America/New_York`; C002 uses `America/Los_Angeles`. Appointments are
  interpreted in the selected clinic's timezone; DST gaps/ambiguities are
  clarified rather than guessed.
- There is no allergy service or allergist in the data. The assistant must say so
  and offer general practice as an initial assessment, never invent a specialist.
- Doctor consultation fees and treatment prices are distinct; no combined total
  is invented.
- Assume otherwise valid requested slots are available; operating hours are not
  enforced as availability.

## Honest limitations

- Single patient (P001), single shared demo password, one backend worker.
- SQLite and in-process per-conversation locks, not a distributed queue.
- No cancellation/rescheduling, registration, scheduling conflict detection,
  diagnosis, prescribing, streaming, or transcript summarization.
- Automatic deployment requires the VM, tailnet policy, Cloudflare route, and
  credentials described in the implementation plan; the workflow fails closed
  if they are absent. It does not rebuild on the VM.
- The included live evaluation report covers the recorded run only; mocked agent
  tests are not evidence of live-model quality.

## Repository map

```text
backend/app/{api,auth,db,services,agent,retrieval}  FastAPI + agent
backend/tests/{api,auth,persistence,agent,retrieval}
backend/evals/                                     live-model cases
frontend/                                          React workbench
vendor/triage/                                     pinned design system (MIT)
tests/e2e/                                         Playwright + model stub
scripts/{check.sh,smoke_test.py,deploy.sh}
compose{,.local,.ci}.yaml  Dockerfile
.github/workflows/{ci,deploy}.yml
docs/contracts.md                                  frozen cross-package contract
```
