# Contributing to ClinicPilot

## Local setup

1. Copy `.env.example` to `.env` and fill in `DEEPSEEK_API_KEY`.
   Development defaults use prefix `/demo/` and dev password
   `clinicpilot-demo`.
2. Backend:
   ```bash
   uv sync --project backend --locked --group dev
   uv run --project backend alembic -c backend/alembic.ini upgrade head
   (cd backend && uv run python -m app.db.seed)
   uv run --project backend uvicorn app.main:app --app-dir backend --port 8000
   ```
3. Frontend (second terminal):
   ```bash
   cd frontend && npm ci && npm run dev
   ```
   Vite proxies `/demo` to `http://127.0.0.1:8000`.
4. Open `http://127.0.0.1:5173/demo/` and log in with the development password.

Production runs the built assets from one container:

```bash
docker compose -f compose.yaml up --build -d
```

## Change flow

- `main` is the deployable branch. Feature work: one branch and one worktree
  per change; merge only after the local gate is green.
- Run `bash scripts/check.sh` before opening a PR. CI runs the same gates plus
  the container smoke test and the aggregate `quality` status.
- Never commit `.env`, databases, model caches, generated patient data, or
  secrets. Gitleaks is part of CI.
- Database changes require an Alembic migration. Keep migrations
  backward-compatible for the automatic deployment rollback window.
- UI changes must pass the vendored strict Triage lint; do not weaken rules to
  make them pass.

## Tests

| Suite | Location | Needs |
| --- | --- | --- |
| Persistence/API | `backend/tests/{api,persistence}` | temporary SQLite |
| Auth | `backend/tests/auth` | temporary SQLite |
| Agent/retrieval | `backend/tests/{agent,retrieval}` | deterministic model stub |
| Browser/container | `tests/e2e` | production image + model stub |
| Live evaluation | `backend/evals/run.py` | DeepSeek key (manual/nightly) |

Report mocked agent behaviour separately from live-model quality. Do not assert
exact generated prose; assert facts, source records, valid actions, state
transitions, and database effects.
