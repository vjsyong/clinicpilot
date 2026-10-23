#!/usr/bin/env bash
#
# Local full gate. Mirrors the required CI checks without needing a DeepSeek
# key, a GPU, or production credentials.
#
#   bash scripts/check.sh
#   SKIP_INSTALL=1 bash scripts/check.sh   # reuse existing envs/node_modules
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SKIP_INSTALL="${SKIP_INSTALL:-0}"

step() {
    printf '\n==> %s\n' "$1"
}

if [[ "$SKIP_INSTALL" != "1" ]]; then
    step "Install backend and frontend dependencies"
    uv sync --project backend --locked --group dev
    (cd frontend && npm ci)
fi

step "CI change classifier tests"
python3 scripts/ci/changed_domains_test.py

step "CI script lint"
uv run --project backend ruff check scripts/ci
uv run --project backend ruff format --check scripts/ci

step "Backend lint"
uv run --project backend ruff check backend

step "Backend format check"
uv run --project backend ruff format --check backend

step "Backend type check"
uv run --project backend mypy backend/app

step "Backend tests"
uv run --project backend pytest backend/tests -q

step "Frontend lint, type check, tests and build"
(cd frontend && npm run lint && npm run typecheck && npm test && npm run build)

step "Design-system strict lint"
triage_lint="${TRIAGE_LINT:-}"
if [[ -z "$triage_lint" ]]; then
    if [[ -f "$ROOT/vendor/triage/lint/triage_lint.py" ]]; then
        triage_lint="$ROOT/vendor/triage/lint/triage_lint.py"
    elif [[ -f /home/xrim/triage-design-system/lint/triage_lint.py ]]; then
        triage_lint="/home/xrim/triage-design-system/lint/triage_lint.py"
    fi
fi
if [[ -z "$triage_lint" || ! -f "$triage_lint" ]]; then
    printf 'triage lint not found; set TRIAGE_LINT or vendor vendor/triage\n' >&2
    exit 1
fi
python3 "$triage_lint" "$ROOT" --strict

step "Compose configuration"
docker compose -f compose.yaml config --quiet
CLOUDFLARE_TUNNEL_TOKEN="${CLOUDFLARE_TUNNEL_TOKEN:-local-validation-token}" \
    docker compose --profile tunnel -f compose.yaml config --quiet
docker compose -f compose.yaml -f compose.local.yaml config --quiet
docker compose -f compose.yaml -f compose.ci.yaml config --quiet

printf '\nAll local gates passed.\n'
