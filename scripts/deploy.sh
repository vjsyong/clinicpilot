#!/usr/bin/env bash
# Deploy one already-published ClinicPilot image to /opt/clinicpilot.
#
# Usage:
#   scripts/deploy.sh --sha <full-commit-sha> --image <registry/repo:tag>
#
# The image is pinned to its digest before use. Migrations run as a separate
# release step. The SQLite volume is never deleted or restored during a
# rollback; only the application container image is reverted.
#
# Environment (from /opt/clinicpilot/.env unless already set):
#   DEPLOY_PATH              default /opt/clinicpilot
#   PUBLIC_BASE_URL          e.g. https://dk.seanyong.xyz
#   GHCR_TOKEN_FILE          optional read-only GHCR token file
#   CLINICPILOT_HEALTH_TIMEOUT default 120 seconds
set -euo pipefail

SHA=""
IMAGE=""
EXPECTED_DIGEST=""
DEPLOY_PATH="${DEPLOY_PATH:-/opt/clinicpilot}"
HEALTH_TIMEOUT="${CLINICPILOT_HEALTH_TIMEOUT:-120}"
PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-https://dk.seanyong.xyz}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --sha) SHA="${2:-}"; shift 2 ;;
    --image) IMAGE="${2:-}"; shift 2 ;;
    --digest) EXPECTED_DIGEST="${2:-}"; shift 2 ;;
    --deploy-path) DEPLOY_PATH="${2:-}"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ ! "$SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "deploy: --sha must be a full 40-hex commit" >&2
  exit 2
fi
if [[ -z "$IMAGE" ]]; then
  echo "deploy: --image is required" >&2
  exit 2
fi
if [[ ! -f "$DEPLOY_PATH/.env" ]]; then
  echo "deploy: $DEPLOY_PATH/.env is missing" >&2
  exit 2
fi

cd "$DEPLOY_PATH"

set -a
# shellcheck disable=SC1091
. ./.env
set +a

STATE_DIR="$DEPLOY_PATH/state"
mkdir -p "$STATE_DIR"
PREVIOUS_IMAGE=""
if [[ -f "$STATE_DIR/current-image" ]]; then
  PREVIOUS_IMAGE="$(cat "$STATE_DIR/current-image")"
fi

log() { printf '[deploy] %s\n' "$*" >&2; }

if [[ -n "${GHCR_TOKEN_FILE:-}" && -f "$GHCR_TOKEN_FILE" ]]; then
  GHCR_USER="${GHCR_USER:-$(printf '%s' "$IMAGE" | cut -d/ -f2)}"
  if ! printf '%s' "$(cat "$GHCR_TOKEN_FILE")" \
      | docker login ghcr.io --username "$GHCR_USER" --password-stdin >/dev/null 2>&1; then
    log "registry login failed"
    exit 1
  fi
fi

log "pulling $IMAGE"
if ! docker pull "$IMAGE" >/dev/null; then
  log "image pull failed"
  exit 1
fi

DIGEST="$(docker image inspect --format '{{index .RepoDigests 0}}' "$IMAGE" | sed 's/.*@//')"
if [[ ! "$DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  log "could not resolve a registry digest for the candidate image"
  exit 1
fi
if [[ -n "$EXPECTED_DIGEST" && "$DIGEST" != "$EXPECTED_DIGEST" ]]; then
  log "published digest does not match the deployed digest"
  exit 1
fi
REPOSITORY="${IMAGE%@*}"
PINNED_IMAGE="${REPOSITORY}@${DIGEST}"
log "deploying $PINNED_IMAGE"

run_migrations() {
  CLINICPILOT_IMAGE="$1" docker compose -f compose.yaml run --rm --no-deps \
    --entrypoint alembic app -c backend/alembic.ini upgrade head
}

wait_ready() {
  local deadline=$((SECONDS + HEALTH_TIMEOUT))
  while (( SECONDS < deadline )); do
    if docker compose -f compose.yaml exec -T app python -c \
      "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=3).read()" \
      >/dev/null 2>&1; then
      return 0
    fi
    sleep 3
  done
  return 1
}

public_checks() {
  [[ -n "${PUBLIC_BASE_URL:-}" ]] || return 0
  local prefix="${DEMO_PATH_PREFIX:-}"
  [[ -n "$prefix" ]] || { log "DEMO_PATH_PREFIX missing; cannot run public probes"; return 1; }
  local base="${PUBLIC_BASE_URL%/}"
  local login_status wrong_status unauth_status health_status ready_status
  login_status="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 "$base$prefix/login" || true)"
  wrong_status="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 "$base/definitely-not-the-prefix/" || true)"
  unauth_status="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 "$base${prefix}api/bookings" || true)"
  health_status="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 "$base/healthz" || true)"
  ready_status="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 "$base/readyz" || true)"
  log "public probes: login=$login_status wrong_prefix=$wrong_status unauth_api=$unauth_status health=$health_status ready=$ready_status"
  [[ "$login_status" == "200" && "$wrong_status" == "404" && "$unauth_status" == "401" ]]
  [[ "$health_status" == "404" && "$ready_status" == "404" ]]
}

rollback() {
  if [[ -z "$PREVIOUS_IMAGE" ]]; then
    log "no previous image recorded; cannot roll back the first deployment"
    return 1
  fi
  log "rolling back application image only (database volume retained)"
  if ! CLINICPILOT_IMAGE="$PREVIOUS_IMAGE" docker compose -f compose.yaml up -d --no-build app; then
    return 1
  fi
  wait_ready
}

if ! run_migrations "$PINNED_IMAGE"; then
  log "migration step failed; application image was not changed"
  exit 1
fi

if ! CLINICPILOT_IMAGE="$PINNED_IMAGE" docker compose -f compose.yaml up -d --no-build app; then
  log "application update failed"
  rollback || true
  exit 1
fi

if ! wait_ready || ! public_checks; then
  log "post-deploy verification failed"
  rollback || true
  exit 1
fi

printf '%s\n' "$PINNED_IMAGE" > "$STATE_DIR/current-image"
printf '%s\n' "$DIGEST" > "$STATE_DIR/deployed-digest"
printf '%s\n' "$SHA" > "$STATE_DIR/deployed-sha"
log "deployed sha=$SHA digest=$DIGEST"
