#!/usr/bin/env bash
# Purge worktrees whose branch is fully merged into the main branch.
#
# Called from .githooks/post-merge after a merge into the main branch. A
# feature branch that is fully merged into <main> has no unique commits, so
# its worktree and branch are safe to remove. This is the automatic teardown
# for the "one feature = one branch + one worktree" flow: merge the branch in
# the main checkout and its worktree cleans itself up.
#
# Safety: a worktree with uncommitted (non-ignored) changes is SKIPPED, never
# force-removed. Only gitignored artifacts (e.g. .codegraph/, node_modules/)
# are allowed to ride along, which is why the remove uses --force AFTER the
# clean check.
#
# Idempotent + self-healing: it sweeps every merged branch with a worktree, so
# a worktree missed earlier is cleaned up on the next merge into main.
#
# Usage:
#   .githooks/purge-merged-worktrees.sh [main-branch]   # default: main
#
# Always exits 0: it is best-effort and must never fail a merge.

set -uo pipefail

MAIN="${1:-main}"

# Only act in a checkout that is sitting on the main branch. A merge inside a
# feature worktree (e.g. syncing main in) must not trigger a purge.
cur_branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)" || exit 0
[ "$cur_branch" = "$MAIN" ] || exit 0

# Branches fully merged into the current HEAD, minus the main branch itself.
merged="$(git branch --merged HEAD --format='%(refname:short)' 2>/dev/null \
  | grep -v -x "$MAIN" || true)"
[ -n "$merged" ] || exit 0

main_top="$(git rev-parse --show-toplevel 2>/dev/null)"
wt_list="$(git worktree list --porcelain 2>/dev/null)"

for br in $merged; do
  # Map branch -> worktree path from the registered worktrees.
  path="$(printf '%s\n' "$wt_list" | awk -v b="$br" '
    /^worktree / { p = substr($0, 10) }
    /^branch /   { if ($2 == "refs/heads/" b) print p }')"
  [ -n "$path" ] || continue
  # Never touch the main checkout itself.
  [ "$path" = "$main_top" ] && continue

  # Only remove when there is no real uncommitted work. git status --porcelain
  # already ignores gitignored files; additionally drop the .codegraph/ index,
  # which the post-checkout hook itself creates and which shows as untracked in
  # any worktree whose HEAD predates the .gitignore entry for it. Regenerable,
  # so it never blocks a purge. Real source changes still do.
  dirty="$(git -C "$path" status --porcelain 2>/dev/null \
    | sed -E 's/^.. //' | grep -v -E '^\.codegraph/' || true)"
  if [ -n "$dirty" ]; then
    echo "purge: keeping worktree for '$br' ($path): has uncommitted changes."
    continue
  fi

  if ! git worktree remove --force "$path" >/dev/null 2>&1; then
    echo "purge: failed to remove worktree for '$br' ($path)." >&2
    continue
  fi
  if git branch -d "$br" >/dev/null 2>&1; then
    echo "purge: removed merged worktree + branch '$br' ($path)."
  else
    echo "purge: removed worktree for '$br' ($path); kept branch."
  fi
done

exit 0
