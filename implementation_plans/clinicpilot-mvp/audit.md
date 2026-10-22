# ClinicPilot MVP — implementation-plan audit

Date: 2026-10-22. **Original audit outcome: Needs Revision.**

**Remediation status:** all eight findings are fixed and deployed from revision
`300963ec2ac5fe28d5f84c8c6f21e8986cac59bf` (CI run 39765211059, deploy run
39765963762, digest
`sha256:987fd915472eb23082d783cb200993d0e826d3384bbb2713aa3031a4db2c4e97`).
Public `/healthz` and `/readyz` now return `404`; login, wrong-prefix, and
unauthenticated-API probes remain correct.

At the audited revision, the normal booking flow, authentication boundaries,
persistent storage, CI, and exact-image deployment were substantially
implemented. However, required confirmation and recovery behavior failed under
reproducible error conditions. The existing green checks and blanket acceptance
passes did not establish those invariants.

## Scope and evidence

- Contract: `implementation_plans/clinicpilot-mvp/plan.md`, particularly §§4–13,
  the WP0–WP8 contracts, and the AC1–AC15 / TEST1–TEST6 matrix; supplemented by
  `docs/contracts.md`.
- Frozen source: **`bfbd438a5f46ef39b69b5481f2a73b761547f16d`**, exported with
  `git archive` to `/tmp/opencode/clinicpilot-audit-bfbd438-20261022`.
- Concurrent UI work advanced HEAD to `8d7a19f` during the audit. Its changes are
  limited to `frontend/src/App.tsx`, `frontend/src/workbench.css`, and
  `tests/e2e/workbench.spec.ts`. It is excluded from the frozen-tree validation;
  all eight findings below concern files unchanged by that commit.
- Focused baseline verification: **102 tests passed in 13.02 s**, covering API,
  auth, persistence, controller, real controller/service integration, REST tools,
  tool schemas, retrieval documents, and retrieval index tests.
- Authoritative Triage strict lint on the frozen tree: **100/100, zero findings**.
- Additional audit-only regressions: **8 failed, 1 passed in 2.36 s**. The eight
  failing assertions represent six defects; three are alternative phrasings of
  the same unsupported-success defect. The existing guard's `Booking confirmed.`
  case passed. These checks use temporary SQLite, deterministic model responses,
  real services, and the real booking HTTP route through ASGI transport.
- Read-only public probes: `/healthz` **200**, `/readyz` **200**, a wrong prefix
  **404** at `https://dk.seanyong.xyz`.
- GitHub API independently confirms successful CI run
  [39753090072](https://github.com/vjsyong/clinicpilot/actions/runs/39753090072),
  including all four quality jobs, aggregate quality, and image publication.
  It also confirms successful deployment run
  [39753860541](https://github.com/vjsyong/clinicpilot/actions/runs/39753860541).
  The required `quality` branch-protection check was verified through the API.
- Read-only Proxmox/guest inspection confirms VM 106 `clinicpilot-demo` running
  on `enterprise`, with 2 vCPU, 4096 MiB RAM, and a 40 GiB disk. The live app's
  image reference and deployment state both identify source
  `f07e9422819de61ca053d2ca9f6f87a3a745e22b` and digest
  `sha256:e78f80cc14d8b83aeb1937a115b07e9bf9baa1190ad35cd5759c10919648c485`.
  Its data mount is `clinicpilot_data` at `/app/data`.
- The eight-case live-model evaluation, clean-setup rehearsal, and rollback drill
  are recorded evidence from the existing reports, not newly repeated checks.
  This audit did not run the full repository gate or initiate a deployment.

Line references below refer to the frozen source. Application changes are not
part of this audit report.

## Remediation summary

| ID | Status | Worktree evidence |
| --- | --- | --- |
| AUD-001 | Fixed locally | Presentation is invalidated before every normal turn; failed-interruption regression uses real draft services. |
| AUD-002 | Fixed locally | Same-key create retry plus draft-projection recovery after lost responses; committed booking is reported with an event. |
| AUD-003 | Fixed locally | Startup recovery replays a committed booking response or releases an orphaned turn; restart tests cover both. |
| AUD-004 | Fixed locally, deployment pending | Health routes require a loopback `Host`; public probes in `deploy.sh` require `404`. |
| AUD-005 | Fixed locally | Broader success-claim guard uses canonical text or `No booking was created`; existing bookings use canonical details. |
| AUD-006 | Fixed locally | Idempotency hash covers canonical booking details; same-key/different-details conflicts. |
| AUD-007 | Fixed locally | Production validation rejects the CI/eval provider stub and non-production endpoints. |
| AUD-008 | Fixed locally | All workflow actions are pinned to full commit SHAs. |

## Required findings and implementation-ready closure tasks

### AUD-001 — High: a failed topic change leaves the previous summary authorized

**Type:** reproduced correctness defect. **Plan:** WP1/WP2/WP6; TEST2;
AC5/AC6; §7 confirmation handling. Frozen contract: `docs/contracts.md:179–186`.

**Evidence:** `backend/app/agent/controller.py:141–166, 347–362, 428–442`.
The old presentation is cleared only after a normal turn finishes. If the model
raises during an interruption, that code is skipped and the interruption's user
message is not persisted. The next turn still sees the old summary as the last
assistant presentation and accepts `yes`.

**Reproduction:** present a complete draft → ask the cancellation policy → inject
`ProviderError` → send `yes` without a fresh summary. With real draft services and
the real HTTP booking route, the final turn creates B1005 in the temporary DB.
`test_failed_topic_change_invalidates_old_confirmation` fails.

**Impact:** a response after a topic change can commit the previous appointment
despite the explicit requirement that interruptions invalidate confirmation.

**Closure task:** invalidate both persisted and in-memory presentation markers
before awaiting the provider on any non-confirmation turn; preserve the draft
itself. Coordinate `controller.py`, `services/drafts.py`, and
`services/conversations.py` if interruption persistence is changed. Add a real
service regression in `backend/tests/agent/test_controller_services.py` covering
provider failure before a policy answer and failure after a draft/tool action.

**Done check:** the subsequent `yes` causes zero booking writes; only a newly
presented current summary followed by another affirmative authorizes creation.

### AUD-002 — High: a lost booking response reports failure after a committed write

**Type:** reproduced correctness defect. **Plan:** WP1/WP2/WP6; TEST1/TEST2;
AC7; §§5 and 7 failure recovery.

**Evidence:** `backend/app/agent/tools.py:125–139, 145–172` makes a single POST;
`backend/app/agent/controller.py:184–213, 274–290` converts its transport error
directly into a failure reply. `services/bookings.py:140–143` has already marked
the draft booked in the insert transaction, so
`services/drafts.py:266–279, 304–305` cannot reset that booked draft. A subsequent
turn with a booked draft does not enter confirmation/recovery.

**Reproduction:** let the real booking route return `201` after commit, then have
the HTTP transport drop that response with `httpx.ReadTimeout`. Exactly one
booking exists, the returned draft status is `booked`, but the assistant says
`there is no confirmed appointment` and emits no `booking_created` event. A
repeated confirmation does not reissue the POST or recover the event.
`test_lost_booking_response_recovers_committed_result` fails.

**Impact:** the user receives an incorrect failure, the bookings table is not
automatically refreshed, and the intended same-operation recovery is lost.
The booking endpoint's successful `200` replay support is insufficient by itself.

**Closure task:** implement bounded same-key recovery in `agent/tools.py` and/or
`agent/controller.py`, including recovery when the persisted draft is already
booked. Do not state that no appointment exists while the outcome is uncertain.
Return the canonical saved record and event; retain an uncertainty/retry state
when recovery cannot be completed. Extend `test_controller_services.py` with a
transport that drops the response after the real route commits, and add a chat
retry test in `backend/tests/api/test_chat.py`.

**Done check:** the lost-response path resolves to the same booking ID, repeated
requests use the identical key, exactly one DB row exists, and the recovered
response includes `booking_created`. An unresolved outcome is not described as a
confirmed absence of a booking.

### AUD-003 — High: interrupted in-progress turns never become recoverable

**Type:** reproduced recovery defect. **Plan:** WP1/WP2/WP6; TEST1/TEST2;
AC7/AC10; §5 interrupted-turn recovery.

**Evidence:** `backend/app/services/conversations.py:141–181, 250–261` returns
`in_progress` for any persisted in-progress row without considering age or
process lifetime. `backend/app/main.py:82–115` contains no startup reconciliation.
The exception handlers in `api/chat.py:110–125` cannot run after abrupt process
termination.

**Reproduction:** persist an in-progress turn, advance the injected clock one
hour, start a fresh app lifespan against the same SQLite file, then retry the
same message ID. It remains `in_progress`.
`test_in_progress_turn_is_recoverable_after_restart` fails.

**Impact:** Retry returns `409 turn_in_progress` indefinitely for work that no
longer has an executing worker. If a booking committed before the crash, there
is also no reconciliation of its canonical chat response. `TECH_DOC.md:266–267`
claims stale turns are retryable, but that behavior is absent.

**Closure task:** add conservative single-worker startup/turn reconciliation in
`main.py`, `services/conversations.py`, and the controller's recovery entry point.
Before allowing a side effect to repeat, reconcile the authorized turn/draft
against an already committed booking. Cover both pre-write and post-commit
crashes in `backend/tests/api/test_chat.py` and persistence/agent integration
tests. Preserve retryable rejection of genuinely active duplicates.

**Done check:** an orphaned turn can complete or replay after restart without a
new message ID; the post-commit case returns the existing booking and event with
no duplicate insert. An active duplicate still returns the specified `409`.

### AUD-004 — Medium: internal health routes are published through the tunnel

**Type:** live reproduced routing defect. **Plan:** WP4/WP5/WP7; TEST4/TEST5;
AC8/AC13; §§6 and 12. Frozen contract: `docs/contracts.md:112–118`.

**Evidence:** `compose.yaml:43–48` forwards the tunnel to the whole app, while
`backend/app/main.py:31, 41–44` bypasses prefix enforcement for health routes.
`docs/deployment-record.md:39` confirms the same broad ingress setup. Actual
unauthenticated public GETs to `/healthz` and `/readyz` both returned `200`.
`scripts/deploy.sh:110–120` probes a wrong prefix but never checks public health
route exclusion.

**Impact:** the explicitly internal liveness/readiness surface is publicly
reachable outside the secret prefix. The observed endpoints expose status, not
patient records; this is still a required ingress-boundary violation.

**Closure task:** add the planned prefix allowlist plus a catch-all `404` at the
Cloudflare/tunnel ingress, preserving internal health access for Compose and
deployment. Update `compose.yaml` and the bootstrap/ingress configuration as
needed; add non-mutating public negative probes to `scripts/deploy.sh` and update
`docs/deployment-record.md` with verified routing evidence.

**Done check:** internal `/healthz` and `/readyz` stay `200`; both public URLs
return `404`; prefixed login and authenticated app behavior continue to work.

### AUD-005 — High: ordinary generated wording can falsely claim booking success

**Type:** reproduced controller-boundary defect using injected model output.
**Plan:** WP2/WP3/WP6; TEST2/TEST3; AC6/AC7/AC11; §7 failure recovery.

**Evidence:** `backend/app/agent/controller.py:81–88, 385–397` recognizes only a
small wording set. With no draft, API call, or saved booking, each of these model
outputs is returned unchanged:

- `Your appointment is confirmed.`
- `Appointment confirmed for 2026-12-15 at 15:00.`
- `I have scheduled your appointment.`

Three parameterized assertions in
`test_unpersisted_booking_success_prose_is_not_forwarded` fail. The recognized
`Booking confirmed.` control passes. The frozen UI renders the unchecked text in
`frontend/src/components/ChatPanel.tsx:120–130` even though events are empty.

**Impact:** the table avoids optimistic inserts, but the chat can still give the
user false assurance that an appointment exists. This contradicts the
application-owned-success invariant. This test establishes the boundary failure;
it does not claim the recorded live-model evaluation emitted these phrasings.

**Closure task:** make booking-status assertions depend on a verified booking
outcome in `agent/controller.py`; for booking-action responses without a saved
record, prefer canonical status/confirmation text over unrestricted success
prose. Expand meaningful negative coverage in
`backend/tests/agent/test_controller.py` and add a browser assertion that a
no-write turn cannot display a confirmation claim. Merely retaining the existing
four-pattern regex does not close this finding.

**Done check:** these straightforward confirmation/scheduling variants cannot
reach the user as success without a persisted result; genuine saved bookings
still produce their canonical ID/details and event.

### AUD-006 — Medium: idempotency hashes operation identity, not canonical details

**Type:** reproduced contract-integrity gap. **Plan:** WP1/WP6; TEST1; AC7;
§5 persistence invariants and mandatory same-key/conflicting-details scenario.

**Evidence:** `backend/app/services/hashing.py:28–29` hashes only `draft_id` and
`draft_version`; `api/bookings.py:59–64` passes that hash to the service. Recovery
in `services/bookings.py:110–120, 205–215` compares only that stored hash.
Changing persisted canonical notes while keeping the same draft version/key
still recovers with `200` instead of an idempotency conflict.
`test_same_key_with_changed_canonical_details_conflicts` fails.

**Scope:** ordinary application slot edits already increment the version. This
reproduction deliberately introduces stored canonical-detail drift; it is not a
demonstrated browser bypass. It exposes the missing comparison explicitly
required by the frozen contract. The existing API conflict test changes the
stored hash manually (`backend/tests/api/test_bookings.py:122–137`) rather than
testing conflicting canonical details.

**Closure task:** construct/compare an immutable canonical booking-payload hash
inside the booking transaction, covering P001, doctor/treatment, resolved slot,
timezone, and notes. Update `services/hashing.py`, `services/bookings.py`, and
`api/bookings.py` together. Add meaningful same-key/same-details and
same-key/different-details HTTP/service tests.

**Done check:** unchanged replay returns the original record; canonical drift
under the same operation key yields `409 idempotency_conflict`; no second row is
inserted. Existing persisted keys/hashes remain recoverable across deployment.

### AUD-007 — Medium: production validation accepts the CI generation stub

**Type:** reproduced configuration-contract defect. **Plan:** WP0/WP4/WP6;
TEST4; AC12; §13 controlled-stub isolation.

**Evidence:** `backend/app/settings.py:104–126` validates a nonempty provider key
but does not reject the CI stub key/model/URL defined in
`compose.ci.yaml:22–24`. With a valid password hash/prefix/internal key,
`APP_ENV=production`, `DEEPSEEK_API_KEY=ci-stub`,
`DEEPSEEK_MODEL=ci-model-stub`, and the model-stub HTTP URL pass
`validate_runtime()`. `test_production_rejects_ci_generation_stub` fails.

**Impact:** production does not fail closed when controlled test-provider
configuration is accidentally reused. The audit did not observe the stub in
the live deployment.

**Closure task:** reject explicit test stub credentials/models/destinations in
production settings and validate the intended production provider endpoint.
Add tests in the settings/auth test area for accepted real-provider settings and
rejected CI-stub combinations, including a stub URL paired with another key.
Keep controlled stub configuration available under `APP_ENV=test`.

**Done check:** the documented CI stub settings cannot start in production; the
normal isolated container/browser suite still starts in test mode.

### AUD-008 — Medium: workflow actions use mutable major tags

**Type:** source-verified plan deviation. **Plan:** WP4/WP7; TEST4/TEST5; AC12;
§13 requirement for pinned action revisions.

**Evidence:** `.github/workflows/ci.yml:29, 32, 184, 187, 282, 366, 375` and
`.github/workflows/deploy.yml:50, 56` use references such as `@v4`, `@v6`, and
`@v3`, rather than immutable action commit SHAs. Other action steps use the same
pattern.

**Impact:** the workflow dependency code can change without a repository
revision, so the delivery definition does not meet the plan's reproducibility
and action-pinning requirement, including in the privileged deploy workflow.
This is not a claim that the successful recorded runs were compromised.

**Closure task:** pin every external action in both workflows to a verified full
commit SHA, optionally retaining the release version in a comment. Validate the
workflow syntax and run normal CI for the resulting trusted revision.

**Done check:** every external `uses:` action has an immutable SHA reference;
required jobs and exact-tested-image promotion still pass.

## Work-package traceability

| ID | Audit outcome | Evidence / remaining closure |
| --- | --- | --- |
| WP0 | Pass With Follow-Up | Standalone Git root verified; frozen contracts, locked dependencies, error/clock/service interfaces exist. Production stub validation remains AUD-007. |
| WP1 | Needs Revision | Real API/auth/persistence checks pass; AUD-001/AUD-002/AUD-003/AUD-006 prevent confirmation/recovery/integrity closeout. |
| WP2 | Needs Revision | Retrieval, narrow schemas, bounded tool loop, patient context, real HTTP tools implemented; AUD-001/AUD-002/AUD-003/AUD-005 remain. Live quality has an existing eight-case recorded pass. |
| WP3 | Pass With Follow-Up | Frozen browser flow has successful CI evidence; source confirms text-only model rendering, same-ID retry, booking-event refetch, and relative URLs; strict Triage lint passes. Chat assurance still depends on AUD-005. Concurrent tab changes excluded. |
| WP4 | Needs Revision | Packaged browser/restart CI and tested-image publication genuinely passed; AUD-004/AUD-007/AUD-008 remain. |
| WP5 | Needs Revision | Dedicated VM exists with the intended shape. Node/storage and runner deviations are documented below; public health-route exclusion fails AUD-004. |
| WP6 | Needs Revision | Application is integrated, but passing normal-path checks does not close the reproduced safety/recovery defects. A prior independent-review closeout artifact was not located. |
| WP7 | Needs Revision | Actual exact-digest deployment and branch check verified; AUD-004/AUD-008 and the runner-model deviation remain. Rollback has a documented forced-failure drill, not a newly observed drill. |
| WP8 | Pass With Follow-Up | README/technical/evaluation/deployment documents exist and clean setup was previously recorded. Correct stale claims and acceptance statuses after findings close. |

## Acceptance traceability

“Recorded” below means existing evidence was inspected, rather than that the
operation was repeated during this audit. A passing row does not override a
related required finding.

| ID | Audit assessment | Evidence / finding |
| --- | --- | --- |
| AC1 | Pass | Both seed tests rerun; stable source counts and retention of a new booking. |
| AC2 | Pass With Follow-Up | Source metadata/document/index checks rerun; live clinic-hours/policy results recorded in `docs/evaluation-report.md`. Live quality not rerun. |
| AC3 | Pass With Follow-Up | Paraphrase retrieval test rerun; D104/T005 routing recorded in live evaluation. |
| AC4 | Pass With Follow-Up | Unsupported-service/index checks and explicit prompt policy; live allergy-honesty result recorded. |
| AC5 | Needs Revision | Normal correction/interruption tests pass, but a failed interruption leaves old confirmation valid: AUD-001. |
| AC6 | Needs Revision | Ordinary no-write/correction checks pass; error-path confirmation and unsupported success prose fail: AUD-001/AUD-005. |
| AC7 | Needs Revision | Real REST creation/replay works normally; lost-response and interrupted-turn recovery fail; canonical-detail conflict comparison is incomplete: AUD-002/AUD-003/AUD-006. |
| AC8 | Pass for API/session isolation; routing gap | Wrong-password, unauthenticated API, foreign-session ownership, expiry/logout and CSRF checks rerun. Internal-only public routing requirement fails AUD-004. |
| AC9 | Pass for tested patient boundaries | P002 chat rejection, foreign-patient service rejection, and no-patient model-tool schemas verified through tests/source. |
| AC10 | Pass for stored bookings; recovery gap | Engine/app restart retention checks rerun; container restart CI independently confirmed. Live volume exists. Interrupted operation recovery still fails AUD-003. |
| AC11 | Pass normal path; Needs Revision for assurance | Successful packaged browser flow in verified CI; source confirms DB refetch. AUD-002/AUD-005 affect error-path UI truthfulness. |
| AC12 | Pass recorded CI; Needs Revision for full contract | All required CI jobs really passed; stub isolation and immutable action references fail AUD-007/AUD-008. |
| AC13 | Pass promotion; ingress follow-up | Published/deployed SHA/digest match verified on live VM and successful workflow. Public health exclusion fails AUD-004; runner deviation below. |
| AC14 | Recorded pass, limited independent evidence | Forced readiness-failure rollback/data-retention drill described in `docs/deployment-record.md:86, 102–105`; not repeated on production. |
| AC15 | Pass With Follow-Up | Clean disposable setup recorded. Correct contradictory technical/deployment statements and unsupported unconditional acceptance claims. |

## Stable test-group traceability

| ID | Audit assessment | Evidence / gap |
| --- | --- | --- |
| TEST1 | Needs Revision | Real persistence/API checks passed; AUD-002/AUD-003/AUD-006 need regression coverage. |
| TEST2 | Needs Revision | Normal controller/retrieval checks passed; AUD-001/AUD-002/AUD-003/AUD-005 reproduce missing failure-path guarantees. |
| TEST3 | Pass With Follow-Up | API/auth checks rerun; browser CI independently confirmed; add a no-write/no-success-claim assertion for AUD-005. |
| TEST4 | Needs Revision | Container/browser/restart jobs genuinely green; AUD-004/AUD-007/AUD-008 remain. |
| TEST5 | Pass With Follow-Up | Trusted-push guard, serialized deployment, artifact/digest provenance and deployed state verified; health-route exclusion fails. Rollback drill is recorded evidence; runner architecture differs from plan. |
| TEST6 | Pass With Follow-Up | Eight-case live evaluation and clean-setup walkthrough recorded; not newly repeated. Documentation corrections and representative failure-path cases remain. |

## Documented deviations, risks, and evidence follow-ups

1. **VM location/storage deviation:** the plan specifies `cerritos`/`data1`;
   the observed VM is on `enterprise`, with `local-lvm` recorded in
   `docs/deployment-record.md:11–28`. The stated reason is missing KVM support on
   `cerritos`. Hardware shape matches. Record this as an explicit plan variance;
   documentation alone is not evidence that the original requirement was amended.

2. **Persistent deployment runner:** the plan specifies an ephemeral
   GitHub-hosted Tailscale runner with dedicated tags/SSH-only policy. The workflow
   uses `[self-hosted, linux, x64]` and a persistent tailnet member instead
   (`deploy.yml:7–10, 31`; `deployment-record.md:83, 96–101`). Dedicated tag/ACL
   enforcement was not independently established. The workflow also writes a
   persistent deploy key into `$HOME/.ssh` (`deploy.yml:76–90`) with no cleanup
   step. Validate runner job isolation and SSH-only tailnet access, scope/clean up
   credential files, and record the accepted architecture before calling WP5/WP7
   fully plan-conformant. This audit establishes the source/document variance,
   not a demonstrated PR credential theft.

3. **Evidence documents need reconciliation:**
   `TECH_DOC.md:271–274` still says remote CI, GHCR promotion, branch protection,
   and rollback were not exercised, contradicting later verifiable records.
   `docs/verification-summary.md:15–17` marks AC5–AC7 unconditionally passed,
   despite AUD-001/AUD-002/AUD-003/AUD-005/AUD-006. The plan's status line still
   says implementation has not started. Update these artifacts with a dated
   status/closeout record; keep plan requirements distinct from execution evidence.

4. **Review closeout evidence:** the plan requires a focused independent review
   before public deployment (WP6, §0). No earlier review/closure report was found
   among the plan and evidence documents. This audit supplies a current review,
   but cannot establish that the historical pre-deploy review happened. Record
   explicit disposition and validation for the findings before the next closeout.

## Reproduction commands

Focused baseline command, run from the frozen snapshot:

```bash
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=/tmp/opencode/clinicpilot-audit-bfbd438-20261022/backend \
/home/xrim/clinicpilot/backend/.venv/bin/python -m pytest \
  backend/tests/api backend/tests/auth backend/tests/persistence \
  backend/tests/agent/test_controller.py \
  backend/tests/agent/test_controller_services.py \
  backend/tests/agent/test_tools.py backend/tests/agent/test_schemas.py \
  backend/tests/retrieval/test_documents.py backend/tests/retrieval/test_index.py \
  -q -p no:cacheprovider \
  --basetemp=/tmp/opencode/clinicpilot-audit-baseline-db-20261022
```

The local audit regression harness is retained separately at
`/tmp/opencode/clinicpilot_plan_audit_repros_20261022.py`. It encodes the expected
contract behavior, so its eight assertion failures are the reproduced findings:

```bash
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=/tmp/opencode/clinicpilot-audit-bfbd438-20261022/backend \
/home/xrim/clinicpilot/backend/.venv/bin/python -m pytest \
  -c /tmp/opencode/clinicpilot-audit-bfbd438-20261022/backend/pyproject.toml \
  -p tests.conftest /tmp/opencode/clinicpilot_plan_audit_repros_20261022.py \
  -q --tb=short -p no:cacheprovider \
  --basetemp=/tmp/opencode/clinicpilot-audit-repro-db-20261022
```

Public negative probes require no private demo prefix or password:

```bash
curl -sS --max-time 20 -o /dev/null -w '%{http_code}\n' https://dk.seanyong.xyz/healthz
curl -sS --max-time 20 -o /dev/null -w '%{http_code}\n' https://dk.seanyong.xyz/readyz
```

## Closeout order

1. Fix AUD-001/AUD-002/AUD-003 and their real-service failure-path regressions.
2. Fix AUD-005 and the public-route boundary AUD-004.
3. Close AUD-006/AUD-007/AUD-008, resolve documented plan variances, and reconcile
   the evidence documents.
4. Validate a newly frozen integrated tree with the required gates, then verify
   its trusted exact-image promotion and non-mutating public routing checks.
   Preserve the existing database and keep live-model quality evidence separate
   from deterministic safety checks.
