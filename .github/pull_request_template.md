## Summary

<!-- What changed, why, and which work package owns it. -->

Work package:
Branch/worktree:
Closes:

## Contract and safety review

- [ ] No change to the frozen contract in `docs/contracts.md` without an
      explicit integrator-approved update.
- [ ] No production prefix, password, API key, internal key, tunnel token, or
      other secret is present in Git, build args, frontend build variables, or
      the image.
- [ ] The model still cannot choose the patient, tool URL, credentials,
      idempotency key, or booking success.
- [ ] Booking writes still require a complete draft, a just-presented summary,
      and an unambiguous affirmative; corrections require reconfirmation.
- [ ] Browser routes remain beneath `DEMO_PATH_PREFIX`; wrong-prefix requests
      are `404`, and unauth API requests are JSON `401`.
- [ ] No raw HTML rendering of model output and no optimistic booking success.

## Checks run

- [ ] `bash scripts/check.sh`
- [ ] Backend: ruff lint, format check, mypy, pytest
- [ ] Frontend: `npm ci && npm run lint && npm run typecheck && npm run build`
- [ ] Vendored Triage strict lint (no weakened rules)
- [ ] Compose config: base, local override, CI override
- [ ] Container/browser acceptance (when backend/frontend integration is ready)
- [ ] Security: gitleaks, pip-audit, npm audit

Commands and actual results:

```text
paste exact commands and outcomes
```

## Acceptance evidence

Map the change to the acceptance matrix; write `n/a` where genuinely not
applicable.

- [ ] AC1 seed repeatability
- [ ] AC2 grounded Q&A
- [ ] AC3 symptom routing
- [ ] AC4 unsupported-service honesty
- [ ] AC5 draft management
- [ ] AC6 confirmation protects writes
- [ ] AC7 persistence and retry safety
- [ ] AC8 authentication and ownership
- [ ] AC9 fixed-patient scope
- [ ] AC10 persistent database across restart
- [ ] AC11 working browser flow
- [ ] AC12 reproducible CI without production secrets
- [ ] AC13 automatic deployment (WP7)
- [ ] AC14 safe deployment failure (WP7)
- [ ] AC15 reproducible submission (WP8)

Evidence (test names, CI run, screenshots/traces, observations):

## Worker completion report

Package:
Outcome:
Files changed:
Contracts changed:
Checks run:
Acceptance evidence:
Unresolved issues:
Integration notes:
Secrets/infrastructure changes (names/resources only):
