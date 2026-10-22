# Verification summary

Recorded: 2026-10-22. This maps the plan's acceptance matrix to actual evidence.
It distinguishes local/manual verification from remote GitHub Actions that were
not run.

## Local and deployed evidence

| ID | Status | Evidence |
| --- | --- | --- |
| AC1 | pass | `test_seed_twice_is_stable_and_retains_new_booking`; seeding twice against a temp DB left counts unchanged and retained bookings created after the first seed. |
| AC2 | pass | Live eval `clinic-hours` and `cancellation-policy`; public live question returned 8:00/24-hour facts with `clinics.csv:C001` among sources. |
| AC3 | pass | Live eval `knee-routing`; retrieval smoke ("my knee hurts") ranked T005/D104 first; public live draft used D104/T005. |
| AC4 | pass | Live eval `allergy-honesty`; no allergist/service invented, general practice offered. |
| AC5 | pass | Agent/draft tests plus live `multi-turn-booking`, `correction-then-confirm`, and `policy-interruption`. |
| AC6 | pass | Confirmation tests: no write before confirmation, correction bumps version, unrelated yes is refused and re-presents the summary, generated success prose without a write is replaced. |
| AC7 | pass | Booking API tests (201/200/409/422, idempotency hash conflict, lost-response replay) and the real ASGI adapter test; public live booking B1005 persisted once. |
| AC8 | pass | Auth tests: wrong password, session attrs/path, logout revocation, unauth JSON 401, foreign conversation 404, CSRF/origin rejection; public login/401 checks. |
| AC9 | pass | P002 rejected with 403 at the chat/booking boundary; model tools have no patient parameter. |
| AC10 | pass | Backend restart test; container restart E2E; VM application container restart retained B1005. |
| AC11 | pass | Playwright login → draft → summary → `yes` → `booking_created` → table refetch; public browser login → 3 rows → logout. |
| AC12 | pass locally | Backend/frontend/security/container checks run locally with no production secrets; remote GitHub Actions not run (no repository/push authorization). |
| AC13 | not verified | `.github/workflows/deploy.yml` is implemented and actionlint-clean, but no GitHub repository, GHCR publication, or Tailscale OAuth credentials were available/authorized. |
| AC14 | not verified | `scripts/deploy.sh` implements image-only rollback and never deletes the volume, but a first-deployment host has no previous image; automatic rollback was not demonstrated. |
| AC15 | pass | README commands rehearsed in a clean disposable copy (no `.git`, `.venv`, `node_modules`, or `data`); migration/seed/frontend build/start/login/wrong-prefix all behaved as documented. |

## Commands and counts

```text
uv run --project backend pytest backend/tests -q          -> 119 passed
npm run lint / typecheck / build                          -> pass
python3 vendor/triage/lint/triage_lint.py . --strict      -> 100/100, 0 findings
npm run test:e2e:functional                               -> 3 passed
npm run test:e2e:persistence                              -> 1 passed
backend/evals/run.py (deepseek-flash)                     -> 8/8 passed
pip-audit (torch +cpu audited as upstream 2.14.1)         -> no known vulnerabilities
npm audit --audit-level=high                              -> 0 vulnerabilities
gitleaks detect --no-git --redact                         -> no leaks
actionlint ci.yml deploy.yml                              -> clean
bash scripts/check.sh                                     -> all local gates passed
```

## Public deployment checks

- Login page `200`; wrong prefix `404 not_found`; unprefixed API `404`;
  prefixed unauthenticated API `401 unauthorized`.
- Login with the private demo password `303`; session-scoped bookings `200`.
- Login assets (`base.css`, `tokens.css`, `geist.woff2`) `200`.
- Live DeepSeek Q&A returned grounded facts and source records.
- Live booking: D104/T005, 2026-12-15 15:00 → summary → `yes` → B1005.
- Application container restart retained B1005.

## Not run

Remote GitHub Actions, GHCR publication, Tailscale deployment, branch
protection, and automatic rollback. See `docs/deployment-record.md` for the
blocked inputs and the node deviation (cerritos has no KVM; the VM runs on
enterprise with the same shape).
