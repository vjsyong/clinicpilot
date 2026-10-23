#!/usr/bin/env bash
# Ensure a CodeGraph index exists for a git worktree (or any checkout).
#
# CodeGraph keeps one .codegraph/ per project root, so a worktree that lives
# outside the main checkout is a separate project and is NOT covered by the
# main index. Without its own index, an agent working in the worktree gets
# "CodeGraph not initialized" and falls back to grep/read instead of
# codegraph_* queries.
#
# Invoked automatically by .githooks/post-checkout when a new branch or
# worktree is created. Also runnable by hand:
#
#   .githooks/codegraph-init-worktree.sh [--force] [path]   # path defaults to $PWD
#   .githooks/codegraph-init-worktree.sh [--force] --all    # every registered worktree
#
# Exit codes: 0 = indexed or already indexed, 1 = build failed,
#             2 = the codegraph CLI is not on PATH.

set -uo pipefail

# Git exports these to hooks; clear them so codegraph resolves the project
# from the path it is given, not from the hook's git context.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_COMMON_DIR

FORCE=0
ALL_WORKTREES=0
TARGET=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --force) FORCE=1 ;;
    --all) ALL_WORKTREES=1 ;;
    -h | --help)
      echo "Usage: $(basename "$0") [--force] [path|--all]"
      echo "  path defaults to the current directory; --all walks every registered worktree."
      exit 0
      ;;
    -*)
      echo "$(basename "$0"): unknown option '$1'" >&2
      exit 1
      ;;
    *) TARGET="$1" ;;
  esac
  shift
done

if ! command -v codegraph >/dev/null 2>&1; then
  echo "CodeGraph is not on PATH - skipping indexing." >&2
  exit 2
fi

_init_one() {
  local path="$1" log had_index=0 ok=1
  if [ ! -d "$path" ]; then
    echo "CodeGraph: skipping '$path' (not a directory)." >&2
    return 1
  fi
  if [ -f "$path/.codegraph/codegraph.db" ] && [ "$FORCE" -eq 0 ]; then
    return 0
  fi
  [ -d "$path/.codegraph" ] && had_index=1

  log="$(mktemp "${TMPDIR:-/tmp}/codegraph-init-XXXXXX.log")"
  if [ "$had_index" -eq 1 ]; then
    echo "CodeGraph: rebuilding index for $path..."
    (cd "$path" && codegraph index "$path") >"$log" 2>&1 || ok=0
  else
    echo "CodeGraph: building index for $path (first run)..."
    (cd "$path" && codegraph init "$path") >"$log" 2>&1 || ok=0
  fi

  if [ "$ok" -eq 1 ]; then
    rm -f "$log"
    echo "CodeGraph: index ready for $path."
    return 0
  fi
  # Never leave a half-built index for the MCP server to serve.
  [ "$had_index" -eq 0 ] && rm -rf "$path/.codegraph"
  echo "CodeGraph: indexing failed for $path (log: $log):" >&2
  tail -n 5 "$log" >&2
  return 1
}

if [ "$ALL_WORKTREES" -eq 1 ]; then
  if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
    echo "Not inside a git repository; cannot enumerate worktrees." >&2
    exit 1
  fi
  failed=0
  while IFS= read -r line; do
    case "$line" in
      worktree\ *) _init_one "${line#worktree }" || failed=1 ;;
    esac
  done < <(git worktree list --porcelain)
  exit "$failed"
fi

_init_one "${TARGET:-$PWD}"
exit $?
