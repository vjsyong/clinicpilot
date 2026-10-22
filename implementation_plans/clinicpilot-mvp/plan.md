# ClinicPilot MVP — Detailed Implementation Plan

Prepared: 2026-10-22.

Status: implementation not started. This document is the execution contract, not evidence that any application, repository, infrastructure, or CI work has been completed.

## 0. Execution instructions

### Objective

Deliver a working, tested ClinicPilot application that:

1. Answers clinic, doctor, and treatment questions using retrieval.
2. Personalizes responses for patient P001.
3. Retrieves current bookings through a REST tool.
4. Collects booking details over multiple turns.
5. Requires confirmation before creating a booking.
6. Persists bookings through a REST tool.
7. Displays persisted bookings in React.
8. Runs through Docker Compose.
9. Is accessible at `https://dk.seanyong.xyz/<secret-link>/` behind a password page.
10. Passes GitHub Actions CI.
11. Automatically deploys successful `main` builds to a dedicated Proxmox VM.

### Confirmed user decisions

| Area | Decision |
| --- | --- |
| Time budget | Approximately 6–10 focused hours within a 24-hour submission window |
| Priority | Reliability and evaluation before bonus functionality |
| Generation | Official DeepSeek API; OpenAI-compatible client |
| Embeddings | Local model; CPU supported, GPU optional |
| Booking commitment | Always show a summary and obtain confirmation |
| Interruptions | Preserve and resume the booking draft |
| Time interpretation | Selected clinic's local timezone |
| Lost booking response | Recover the same booking using persisted idempotency |
| Demo access | Secret URL prefix plus application password-login page |
| Domain | `dk.seanyong.xyz`, unused hostname |
| Runtime | Dedicated VM provisioned through the Proxmox MCP |
| Repository | Standalone repository at `/home/xrim/clinicpilot`; public GitHub repository named `clinicpilot` |
| CI runners | GitHub-hosted |
| Promotion | Automatic deployment after successful `main` CI |
| Development | Parallel, isolated work packages following Docscan and Sushiro BI conventions |

### Execution rules

- Execute work packages in dependency order.
- Parallelize only the explicitly independent packages.
- One worker owns one branch/worktree.
- Do not change another worker's owned files.
- The integrator owns shared contracts and dependency coordination.
- Do not change a frozen contract silently.
- Run validation against a frozen tree.
- Report actual command results, not intended results.
- Never mark a package complete with failing required checks.
- Register implementation and long-running checks with taildash, best-effort.
- Follow applicable repository and global `AGENTS.md` instructions.
- Do not commit, push, or create a GitHub repository until those Git/GitHub operations are explicitly authorized. Ask for that authorization before the integration/publication phase if it has not already been given.
- Do not put the production password, secret URL suffix, API keys, tunnel token, or private keys into Git or public CI logs.

### Risk and review

Risk tier: **HIGH**, specifically for public authentication, booking confirmation and duplicate prevention, CI deployment credentials, VM provisioning, and persistent data.

Use one focused independent review before the public deployment. Findings must include a reproducible failure or concrete code evidence. The implementer must reassess the actual diff rather than treating this risk label as evidence of correctness.

### Non-goals

Do not implement:

- Patient registration or multi-patient authentication.
- Scheduling conflict detection.
- Booking cancellation or rescheduling.
- Diagnosis or medication prescribing.
- MCP tools for the application.
- A separate AI microservice.
- Kubernetes.
- Streaming responses.
- Transcript summarization.
- A separate vector database.
- A generalized agent framework.
- Long-lived integration branches or elaborate release-qualification machinery.

## 1. Existing environment and source material

### Application repository

Current directory: `/home/xrim/clinicpilot`.

At planning time it contained only the six supplied CSVs. This plan is the first implementation artifact:

```text
dkl_ai_interview_data/
  clinics.csv
  doctors.csv
  treatments.csv
  patients.csv
  patient_bookings.csv
  patient_treatment_history.csv
```

**Important:** At inspection, `git rev-parse --show-toplevel` from this directory returned `/home/xrim`. Establish a standalone repository at `/home/xrim/clinicpilot` before creating branches or worktrees. Do not alter the home-directory repository or stage its unrelated files.

No ClinicPilot symbols, routes, tests, or source-code anchors exist yet. The files and symbol names below are planned implementation anchors, not claims about existing code.

CodeGraph is not initialized for ClinicPilot. Do not assume it is available, initialize it without the user's approval, or repeatedly query the missing index.

### Reference implementations

Use these as patterns, not files to copy wholesale:

```text
/home/xrim/docscan/AGENTS.md
/home/xrim/docscan/.github/workflows/ci.yml
/home/xrim/docscan/tools/check_release.py

/home/xrim/sushiro_bi/AGENTS.md
/home/xrim/sushiro_bi/.github/workflows/ci.yml
/home/xrim/sushiro_bi/.github/workflows/deploy-staging.yml
```

Adopt explicit ownership, isolated worktrees, parallel quality gates, an aggregate required CI check, exact-image deployment, and health-check rollback.

Do not reproduce their Android or distributed-release machinery. Sushiro BI's self-hosted PR-runner configuration is not the runner model for this public submission.

### Design system

Read and follow:

```text
/home/xrim/triage-design-system/AGENTS.md
/home/xrim/triage-design-system/INTERACTION.md
/home/xrim/triage-design-system/spec/rules.json
```

Include a pinned, licensed copy of the necessary assets and lint dependencies so public CI does not depend on a private checkout. The inspected design-system license is MIT; preserve its copyright and license notices, plus separately applicable font/icon licenses.

Do not hand-edit generated design-system files.

### Infrastructure observations

These were read-only observations, not reserved capacity or provisioned resources:

- `enterprise` and `cerritos` were online.
- `cerritos` had approximately 29 GiB available RAM.
- `data1` on `cerritos` had approximately 1.5 TiB available storage.
- `vmbr0` on `cerritos` was active.
- Debian 13 cloud-init template VM 9100 exists on `enterprise`, with a 3 GiB source disk on `local-lvm` and guest-agent support enabled.
- The existing tailnet is in use and includes infrastructure hosts.
- Cloudflare's zone is ready, but the application route still needs configuring.

Recheck state before provisioning. Do not assume credentials, free VM IDs, IP addresses, or permissions have been reserved.

## 2. Fixed technology choices

| Concern | Choice |
| --- | --- |
| Python | 3.12 |
| Backend | FastAPI |
| Validation | Pydantic |
| ORM | SQLAlchemy 2 |
| Database | SQLite |
| Migrations | Alembic |
| Python dependencies | `uv`, committed lockfile |
| Generation client | OpenAI Python SDK using DeepSeek's compatible endpoint |
| Generation model | Configurable; initial value `deepseek-flash` |
| Endpoint | `https://api.deepseek.com` |
| Generation mode | Non-thinking initially |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2`, CPU supported |
| Similarity search | In-memory normalized vectors and cosine similarity |
| Frontend | React, TypeScript, Vite |
| Node | 24 LTS |
| Frontend dependencies | npm with committed lockfile |
| Browser smoke | Playwright |
| Containers | Docker Compose |
| Public ingress | Cloudflare Tunnel |
| Private deployment | Tailscale plus SSH |
| CI | GitHub-hosted runners |
| Registry | GHCR |
| Deployment | Automatic after successful `main` CI |

Resolve compatible dependency versions during WP0 and commit lockfiles when commits are authorized. Workers must not independently upgrade shared dependencies.

Prefer the smallest dependency set that implements these contracts. Do not add LangGraph, LangChain, a message broker, Redis, or a vector server.

## 3. Target repository layout

```text
clinicpilot/
  AGENTS.md
  CONTRIBUTING.md
  README.md
  TECH_DOC.md
  .env.example
  .gitignore
  .dockerignore
  .triagerc.json

  backend/
    pyproject.toml
    uv.lock
    alembic.ini
    migrations/
    app/
      main.py
      settings.py
      contracts.py
      api/
        chat.py
        bookings.py
        health.py
      auth/
        routes.py
        sessions.py
        middleware.py
      db/
        models.py
        session.py
        seed.py
      services/
        bookings.py
        conversations.py
        drafts.py
      agent/
        controller.py
        prompts.py
        schemas.py
        tools.py
        model_client.py
      retrieval/
        documents.py
        embeddings.py
        index.py
      config/
        doctor_treatments.json
    tests/
      api/
      auth/
      agent/
      retrieval/
      persistence/
    evals/
      cases.json
      run.py

  frontend/
    package.json
    package-lock.json
    src/
    tests/

  vendor/
    triage/
      LICENSE
      ...required assets and lint dependencies...

  tests/
    e2e/

  scripts/
    check.sh
    smoke_test.py
    deploy.sh

  docs/
    contracts.md

  dkl_ai_interview_data/
    ...original CSVs...

  Dockerfile
  compose.yaml
  compose.local.yaml
  compose.ci.yaml

  .github/
    CODEOWNERS
    pull_request_template.md
    workflows/
      ci.yml
      deploy.yml

  implementation_plans/
    clinicpilot-mvp/
      plan.md
```

If a proposed file is unnecessary, omit it rather than creating an empty abstraction layer. Preserve the ownership boundaries in section 14.

## 4. Fixed domain assumptions

### Patient

- All application activity belongs to P001.
- The server supplies patient identity to tools.
- The model cannot choose another patient.
- An explicitly supplied `patient_id` other than P001 returns `403`.

### Doctor–treatment compatibility

Store this explicit application assumption in `backend/app/config/doctor_treatments.json`:

```json
{
  "D101": ["T001", "T004"],
  "D102": ["T002"],
  "D103": ["T003"],
  "D104": ["T005"]
}
```

Document that the supplied datasets do not define this relationship. Reject incompatible pairings instead of silently changing the patient's choice.

### Timezones

```text
C001 → America/New_York
C002 → America/Los_Angeles
```

- Interpret appointments in the selected clinic's timezone.
- Inject the current time into agent context.
- Clarify ambiguous AM/PM and relative dates.
- Display the resolved date, time, and timezone before confirmation.
- Reject past dates and invalid/nonexistent local times.
- Clarify ambiguous daylight-saving transitions rather than guessing.
- Resolve the timezone again if the selected doctor/clinic changes.

Assume all otherwise valid requested slots are available. Do not enforce operating hours as availability restrictions.

### Recommendations

- Recommend only services and doctors present in the dataset.
- No allergy-specific service or allergist exists.
- For an allergy consultation, explain that limitation and offer general practice as an initial assessment option.
- Do not diagnose, prescribe medication, or claim specialist allergy care exists.
- Distinguish doctor consultation fees from treatment prices; do not invent a combined total.
- Preserve conditional preparation instructions. For example, fasting for T001 applies if blood tests are scheduled.
- For an explicit life-threatening emergency, prioritize the dataset's emergency instructions rather than continuing a routine booking workflow.

### Shared demo behavior

- Authenticated visitors share P001's persisted bookings.
- Conversations and drafts are isolated by authenticated browser session.
- Starting a new conversation does not delete bookings.

## 5. Database contract

Use migrations. Enable SQLite foreign-key enforcement on every connection.

### Seed tables

Preserve the six source datasets as relational tables:

```text
clinics
doctors
treatments
patients
patient_bookings
patient_treatment_history
```

Preserve source IDs and foreign keys. Use decimal-safe representations for prices, such as integer cents. Keep the original CSVs unchanged.

### Additional tables

#### `demo_sessions`

```text
id
token_hash
created_at
expires_at
revoked_at nullable
```

Store only a hash of the opaque browser session token.

#### `conversations`

```text
id
demo_session_id
patient_id
messages_json
created_at
updated_at
```

`messages_json` preserves the model conversation, including assistant tool calls and matching tool results. Do not inject malformed or incomplete tool-call sequences on a resumed turn.

#### `chat_turns`

```text
id
conversation_id
client_message_id
request_hash
status
response_json nullable
created_at
updated_at
```

Unique constraint: `(conversation_id, client_message_id)`.

Purpose: return an already completed turn without repeating side effects. A repeated message ID with a different request hash returns `409`. An actively processing duplicate returns a retryable in-progress response rather than starting a second turn.

#### `booking_drafts`

```text
id
conversation_id
version
status
doctor_id nullable
treatment_id nullable
local_date nullable
local_time nullable
timezone nullable
starts_at_utc nullable
notes nullable
confirmation_message_id nullable
authorized_turn_id nullable
booking_id nullable
created_at
updated_at
```

### Booking extensions

Add to `patient_bookings`:

```text
starts_at_utc
timezone
idempotency_key nullable, unique
request_hash nullable
created_at
```

Keep source date/time fields where useful for faithful seeding and presentation. Seed bookings receive their clinic timezone and normalized timestamp. Preserve source booking IDs; new IDs must not collide with them.

### Persistence invariants

- Seeding is repeatable.
- Seeding does not overwrite user-created records.
- Booking insert and idempotency handling occur transactionally.
- Never hold a database transaction open during an LLM request.
- A repeated idempotency key returns the original booking.
- The same key with different canonical booking details returns `409`.
- Container recreation retains the database.
- Persist each successful draft mutation before reporting it.
- Recover interrupted turns conservatively; check for an already committed booking before repeating a side effect.

## 6. API contract

All browser-facing routes live beneath a runtime-configured prefix.

```text
Development: /demo/
Production:  /<secret-link>/
```

API paths in this section are relative to that prefix unless stated otherwise.

### Authentication

```text
GET  /login
POST /login
POST /logout
```

- Login uses a shared password.
- Use a maintained password-hashing library; store its hash, not plaintext, in runtime configuration.
- Sessions expire after eight hours.
- Cookies are `HttpOnly`, `Secure` in production, and `SameSite=Lax`.
- Scope the cookie path to the demo prefix.
- Logout revokes the session.
- Protect browser mutations against cross-origin requests.
- Add login throttling.
- Unauthenticated page requests redirect to login.
- Unauthenticated API requests return JSON `401`, not HTML redirects.
- Return `404` outside the configured prefix.
- Production must fail closed if required password/path/credential configuration is absent or contains placeholder values.

### `POST /api/chat`

Request:

```json
{
  "conversation_id": null,
  "message_id": "client-generated-uuid",
  "message": "I would like a knee consultation",
  "patient_id": "P001"
}
```

Rules:

- `conversation_id` may be omitted or null on the first turn.
- `message_id` is required.
- Limit message length.
- A conversation must belong to the current demo session.
- Foreign-session conversation IDs return `404`.
- Serialize turns per conversation.
- Run a single backend worker for this MVP.

Response:

```json
{
  "conversation_id": "uuid",
  "message_id": "uuid",
  "assistant_message": "Which date would you prefer?",
  "sources": [],
  "booking_draft": null,
  "events": []
}
```

A completed draft uses this representation:

```json
{
  "draft_id": "uuid",
  "version": 2,
  "status": "awaiting_confirmation",
  "doctor_id": "D104",
  "doctor_name": "Dr. James Wilson",
  "treatment_id": "T005",
  "treatment_name": "Joint & Pain Consultation",
  "local_date": "2026-11-17",
  "local_time": "15:00",
  "timezone": "America/New_York"
}
```

The date above is a shape example, not a hard-coded runtime date. Tests use an injected clock.

A successful booking adds an event:

```json
{
  "type": "booking_created",
  "booking": {
    "booking_id": "persisted-booking-id"
  }
}
```

The actual `booking` object must use the complete canonical booking representation below. Persist the completed chat response for duplicate-message recovery.

### `GET /api/bookings`

Allowed authentication:

- Browser session.
- Internal booking-tool credential.

Return P001 bookings with:

```text
booking_id
doctor_id / doctor_name
treatment_id / treatment_name
clinic_id / clinic_name
local_date
local_time
timezone
starts_at_utc
status
notes
```

“Next appointment” means the earliest future, non-cancelled appointment, using the injected current time. Historical/completed records must not be presented as an upcoming appointment.

### `POST /api/bookings`

Only the internal tool credential may create bookings. A browser session alone is insufficient for this endpoint.

Request:

```json
{
  "draft_id": "uuid",
  "draft_version": 2
}
```

Header:

```text
Idempotency-Key: booking:<draft-id>:v<version>
```

The server loads canonical details from the draft. It must not trust a second model-generated copy of booking fields.

Validate:

- Draft exists.
- Patient is P001.
- Version matches.
- Confirmation authorization exists for the current version and turn.
- Required details are complete.
- Doctor and treatment exist and are compatible.
- Timestamp is valid and future.
- Idempotency conditions hold.

Perform idempotent recovery before rejecting an already completed draft, while still verifying that the repeated request matches the original operation.

Return:

- `201` for a new booking.
- `200` for successful idempotent recovery.
- `409` for conflicting state or payload.
- `422` for invalid details.

### Health and readiness

Provide separate internal liveness/readiness checks for Compose and deployment scripts. Readiness requires a usable database and loaded retrieval resources. Do not call DeepSeek on every health check.

The tunnel's path allowlist must not publish unprefixed internal health routes. Missing external-provider connectivity should produce a clear chat error rather than deleting local state.

### Error shape

```json
{
  "error": {
    "code": "draft_version_conflict",
    "message": "The booking details changed. Please confirm the updated summary.",
    "retryable": false
  },
  "request_id": "uuid"
}
```

Do not expose stack traces, credentials, or raw provider responses.

## 7. Agent contract

### Tools

Implement these tools:

```text
search_knowledge(query, optional filters)
get_patient_bookings()
update_booking_draft(optional slot changes)
abandon_booking_draft()
create_booking()
```

`get_patient_bookings` and `create_booking` must perform actual HTTP calls to the booking API. The internal destination is configured server-side and remains reachable without traversing Cloudflare.

The model does not supply:

- Patient identity.
- Tool destination URL.
- Internal credentials.
- Idempotency keys.
- Booking-success status.

### Routing

Use tool selection rather than an additional classifier call.

Support mixed requests in one turn. A policy question must not discard an active booking draft. Keep state in the database, not solely in model memory.

### State transitions

```text
no draft
   → collecting_details
   → awaiting_confirmation
   → booking_in_progress
   → booked

collecting_details / awaiting_confirmation → cancelled
changed details → validation → collecting_details or awaiting_confirmation
recoverable external failure → retain draft and recover/retry safely
```

### Draft changes

Every meaningful slot change:

1. Validates proposed values.
2. Increments the version.
3. Clears previous confirmation authorization.
4. Returns missing fields or a complete summary.

Produce confirmation summaries from canonical validated draft data, not independently regenerated details.

### Confirmation handling

For predictable MVP behavior, use a conservative server-side confirmation rule.

A confirmation is valid only when:

1. A complete draft is awaiting confirmation.
2. The last assistant turn presented that draft/version.
3. The user provides an unambiguous affirmative response.

Normalize case, whitespace, and terminal punctuation. Initially support:

```text
yes
yes please
confirm
confirmed
go ahead
book it
yes book it
yes confirm
please book it
```

Anything containing corrections or additional instructions is not accepted by this shortcut.

```text
“yes”                              → eligible confirmation
“yes, but make it Wednesday”       → process as correction
“what is the cancellation policy?” → answer; retain draft
```

For other natural confirmations, ask the user to confirm explicitly rather than risk an unintended write.

After an interruption, either repeat the current summary or require a fresh summary before accepting confirmation. An unrelated “yes” must not authorize an old summary.

### Confirmed execution

On valid confirmation:

1. Persist authorization for the current draft/version and turn.
2. Expose only the booking-creation action for this execution step.
3. Request the model's `create_booking` tool call.
4. Execute the REST request using server-owned details.
5. Store the returned booking ID.
6. Return canonical success information.

`create_booking()` takes no model-selected booking arguments. The server authorizes a specific draft version, not any future draft modification.

### Failure recovery

- If the POST response is lost, repeat using the same key.
- If the model fails after the booking is saved, construct the final confirmation from the saved record.
- Never say “booked” based solely on generated text.
- Keep a valid draft when an external operation fails.
- On recovery from an interrupted turn, check for an existing booking before executing another write.
- A provider retry must not generate a fresh idempotency key for the same operation.

### Execution bounds

Configure:

- Provider timeout.
- Maximum tool rounds per turn.
- Limited retries.
- Maximum conversation history/context budget.

Use validated tool schemas. Do not execute arbitrary tool names. Retain valid tool-call/result pairing when trimming model history.

## 8. Retrieval contract

### Documents

Build one document per knowledge CSV row:

```text
2 clinic documents
4 doctor documents
5 treatment documents
```

Each document has:

```text
document_id
source_file
record_id
text
metadata
```

Include relevant relational context, such as a doctor's clinic name. Do not fabricate descriptive medical claims to improve retrieval.

### Search

1. Resolve exact IDs and known names when available.
2. Embed the query.
3. Rank normalized document vectors.
4. Retrieve relevant records.
5. Hydrate relationships from the database.
6. Return source references.

Use cosine similarity without a vector-database dependency. Pin the embedding-model revision during implementation. Prewarm it before readiness is reported. Cache document vectors with an input/model fingerprint so stale vectors are not reused after a dataset/model change.

### Patient context

Load only P001's relevant profile, allergies, and treatment history.

Bookings must be read through the booking API rather than answered solely from injected history. Do not embed private patient records into the shared knowledge index.

### Grounding

Every returned source includes:

```json
{
  "source_file": "doctors.csv",
  "record_id": "D104"
}
```

Do not present a similarity score as calibrated confidence. Include evaluation cases for paraphrases, especially “my knee hurts,” rather than testing only exact category strings.

## 9. Frontend contract

### Login

- Password form.
- Error feedback.
- Successful redirect.
- Logout.

The backend worker owns login/session logic and any server-rendered login route. The frontend worker supplies presentation/styles through frontend-owned assets. Agree on that boundary in WP0; do not have both workers edit the same template.

### Workbench

- Chat history.
- Message composer.
- Loading state.
- Retry using the same message ID.
- Source references.
- Booking confirmation summary.
- Live bookings table.
- Manual refresh.
- New-conversation action.

Behavior:

- On `booking_created`, refetch bookings.
- On `401`, return to login.
- Never optimistically display a confirmed booking before API success.
- Never render model output as raw HTML.
- Prevent concurrent duplicate submissions while preserving retry after failure.
- Use the existing design-system tokens/components and accessible labels/focus behavior.

### Prefix handling

Build portable frontend assets with relative URLs. Inject a safely encoded runtime configuration containing the prefix when the backend serves the authenticated index page.

Do not bake the production secret prefix into the image. Constrain the prefix to a safe generated slug and safely encode any configuration injected into HTML.

Avoid a broad SPA fallback that turns unknown API paths into `200` HTML. Canonicalize the prefix root with a trailing slash so relative assets resolve correctly.

## 10. Container and runtime contract

### Services

```text
app
cloudflared
```

Use a multi-stage image:

1. Node frontend build.
2. Python application/runtime stage.

The application container serves frontend assets and API.

### Runtime

- Run as a non-root user.
- One backend worker.
- Persistent database directory.
- Model weights available before accepting traffic.
- Health and readiness checks.
- Restart policy.
- No production reload/debug mode.
- Include timezone data.
- Ensure the non-root application user can write its data/cache directories.

### Networking

- Production Compose publishes no application port.
- `cloudflared` reaches the application on the Compose network.
- Preserve outbound connectivity for DeepSeek and tunnel operation.
- A local override binds only to `127.0.0.1`.
- CI disables the tunnel service.
- Worktree/CI Compose project names and volumes must be isolated; do not give every environment the same explicit global volume name.

### Configuration

Support secret-file configuration where appropriate:

```text
DEEPSEEK_API_KEY
DEEPSEEK_MODEL
DEMO_PATH_PREFIX
DEMO_PASSWORD_HASH
INTERNAL_TOOL_KEY
CLOUDFLARE_TUNNEL_TOKEN
DATABASE_URL
```

Use one consistent name for each setting across code, Compose, and documentation. Never print fully rendered production configuration. Do not pass passwords/API keys through frontend build variables or image build arguments.

The secret URL prefix is runtime configuration. A public image must not reveal the production prefix. CI uses a fixed synthetic prefix and temporary credentials.

## 11. Proxmox provisioning contract

### Target

```text
Name: clinicpilot-demo
Node: cerritos
CPU: 2 vCPU
Memory: 4096 MB
Disk: 40 GB
Storage: data1
Bridge: vmbr0
GPU: none
```

Use a free VM ID determined immediately before provisioning.

### Source

```text
Node: enterprise
Template VMID: 9100
Description: Debian 13 cloud-init template
Source storage: local-lvm
```

Proxmox permits direct cross-node cloning only when source storage is shared. The source template here is node-local, so clone locally and then migrate the stopped clone.

### Procedure

1. Confirm target name and selected VM ID do not exist.
2. Recheck source template, node capacity, storage, and network.
3. Full-clone template 9100 on `enterprise`, without starting it.
4. Wait for task completion and inspect task status/log on failure.
5. Migrate the stopped clone and disks to `cerritos`, using `data1`.
6. Wait for task completion.
7. Configure CPU, memory, cloud-init SSH key, networking, and guest agent.
8. Grow disk to 40 GB.
9. Start VM.
10. Wait for guest readiness and cloud-init completion.
11. Verify filesystem expansion.
12. Discover the assigned address.
13. Configure a stable address through a DHCP reservation or a confirmed unused static address.
14. Install Docker, Compose, and Tailscale.
15. Create `/opt/clinicpilot`.
16. Configure deployment access and host-key verification.
17. Record VM ID and non-secret operational details.

Use MCP operations where exposed. Use authenticated host/bootstrap commands for cloud-init fields not exposed by the MCP tool schemas; do not assume every Proxmox API parameter is accepted by every tool.

### Stop conditions

Stop and report if:

- The proposed name/ID already belongs to another resource.
- Template cloning or migration fails.
- SSH/cloud-init access cannot be established.
- An address cannot be safely assigned.
- Required credentials are unavailable.

Do not alter the template or repurpose an unrelated existing VM. Do not delete a newly created VM automatically after a partial provisioning failure; record its identity and failure state for recovery.

## 12. Cloudflare and deployment connectivity

### Public application

```text
https://dk.seanyong.xyz/<secret-link>/
```

- Route only the configured prefix through the tunnel.
- Unmatched hostname paths return `404`.
- The application handles the prefix; Cloudflare does not strip it.
- Bypass caching for the demo initially.
- Authentication/API responses use `Cache-Control: no-store`.
- Set `Referrer-Policy: no-referrer`.
- Protect static assets as well as API routes.
- Disable public API documentation in the hosted configuration.
- Do not introduce third-party analytics or page resources that disclose the URL.

The secret prefix is a discovery barrier, not a replacement for authentication.

### Private deployment

The existing tailnet is available. Configure:

- A dedicated VM tag.
- A dedicated deployment-runner tag.
- Access from deployment runner to VM SSH only.
- Ephemeral GitHub-hosted runner membership.
- Verified SSH host keys.

Normal PR CI receives no tailnet or deployment credentials.

Required deployment credentials include:

```text
TS_OAUTH_CLIENT_ID
TS_OAUTH_SECRET
DEPLOY_SSH_KEY
```

Use repository/environment variables for non-secret host identifiers. Inspect and preserve existing tailnet policy; make only the needed additive rule/tag changes when authorized access exists.

Cloudflare provisioning is a one-time setup. Ordinary application deployments must not recreate the tunnel or DNS record.

## 13. CI/CD contract

### `ci.yml`

Triggers:

```text
pull_request
push to main
```

Default permissions: `contents: read`.

Use GitHub-hosted Linux runners, explicit timeouts, pinned action revisions, locked dependencies, and dependency/build caches. Cancel superseded CI runs for the same PR/ref.

Run all relevant gates initially; changed-path optimization is deferred.

### Parallel jobs

#### Backend

From the repository root:

```bash
uv sync --project backend --locked --group dev
uv run --project backend ruff check backend
uv run --project backend ruff format --check backend
uv run --project backend mypy backend/app
uv run --project backend pytest backend/tests -q
```

Configure pytest to resolve the backend application package consistently. Tests must use temporary databases and an injected clock. Standard tests must not require a live DeepSeek key or GPU.

#### Frontend

Run in `frontend/`:

```bash
npm ci
npm run lint
npm run typecheck
npm run build
```

Run the vendored strict Triage lint against application UI sources, including server-rendered login markup. First validate locally against the authoritative checkout:

```bash
python3 /home/xrim/triage-design-system/lint/triage_lint.py /home/xrim/clinicpilot --strict
```

The public-CI equivalent uses the pinned vendored tooling and same rules, not that machine-specific absolute path. Do not weaken rules merely to make CI pass.

#### Security

- Pinned Gitleaks CLI with redacted output.
- Python dependency audit against resolved dependencies.
- `npm audit --audit-level=high`.

Do not silently suppress findings or print matched secret values.

#### Container

1. Validate CI Compose configuration.
2. Build the production image.
3. Start application plus controlled external-model stub.
4. Run integration/browser smoke.
5. Restart application and verify persistence.
6. Collect redacted failure artifacts.
7. Always clean up the CI project and its temporary volumes.

No Cloudflare connector or production credential is required. The controlled stub replaces the generation provider, not the booking API or database. Ensure test stub configuration cannot accidentally be used by production deployment.

### Aggregate quality gate

Run even when dependencies fail. Pass only if every required quality job succeeded. Unexpected skips, missing statuses, failures, and cancellations do not count as green.

Make this the required PR status when repository permissions allow branch protection. Do not claim branch protection is configured without verifying it.

### Image publication

Only for a push to `main` after quality succeeds:

1. Load the exact image tested by container CI.
2. Publish to GHCR.
3. Tag with full commit SHA.
4. Record image digest and source revision.

Do not rebuild during publication or deployment. Scope registry write permissions to the publication job. Do not publish images from PRs.

### `deploy.yml`

Trigger on successful completion of CI. Before accessing credentials, verify:

```text
workflow event was push
head branch was main
head repository is this repository
CI conclusion was success
```

Do not check out or execute an untrusted PR using this privileged workflow. Use the validated CI head SHA, not a mutable default checkout, to identify the candidate.

Deployment concurrency:

```text
one deployment at a time
cancel-in-progress: false
```

Procedure:

1. Validate candidate commit and image digest.
2. Join Tailscale.
3. SSH using a pinned host key.
4. Skip an obsolete candidate where appropriate; never replace a newer deployed revision with an older queued candidate.
5. Save the currently deployed image reference.
6. Validate deployment configuration without printing secrets.
7. Pull exact image digest.
8. Apply backward-compatible migrations as a separate release step.
9. Update application.
10. Run readiness and public routing/authentication checks.
11. Record deployed revision.
12. Restore the previous image if application health fails.

Do not delete or restore the database during ordinary rollback. Restrict this MVP's automatic migrations to backward-compatible changes. On the first deployment, report failure honestly if there is no prior image to restore.

Public deployment smoke must not create demonstration appointments. Use private readiness checks plus non-mutating public routing/authentication probes; any authenticated probe credential remains in a secret-safe host-side execution context.

## 14. Work packages

Each package below is initially **PENDING**. Completion requires its checks and acceptance evidence, not just code changes.

### WP0 — Foundation and contracts

**Owner:** Integrator. **Dependencies:** None.

**Owned paths**

```text
AGENTS.md
CONTRIBUTING.md
docs/contracts.md
backend/pyproject.toml
backend/uv.lock
backend/app/main.py
backend/app/settings.py
backend/app/contracts.py
frontend package/configuration scaffold
.gitignore
.env.example
```

**Steps**

1. Establish the standalone repository without modifying the parent repository.
2. Preserve source CSVs unchanged.
3. Create application scaffold.
4. Resolve and lock dependencies.
5. Write the contracts from this plan into `docs/contracts.md`.
6. Provide common settings and error representations.
7. Define concrete agent/service interfaces, including injected model client, retrieval, state store, booking HTTP adapter, and clock.
8. Assign login presentation/template ownership explicitly.
9. Define worker ownership and dependency-change procedure.
10. Create branches/worktrees when Git operations are authorized and the repository has a suitable initial commit.

**Required checks / evidence**

- `git rev-parse --show-toplevel` resolves to `/home/xrim/clinicpilot`.
- Backend and frontend scaffolds start.
- Contracts include API, error, draft, and agent/service representations.
- No credentials or runtime databases are tracked.

**Non-goal:** Implementing the business workflow before contracts are frozen.

**BLOCKED if:** Repository setup would alter unrelated home-directory work, or authorization for needed Git operations is missing.

### WP1 — Persistence, booking API, authentication

**Owner:** Backend worker. **Dependencies:** WP0.

**Owned paths**

```text
backend/app/api/
backend/app/auth/
backend/app/db/
backend/app/services/
backend/migrations/
backend/alembic.ini
backend/tests/api/
backend/tests/auth/
backend/tests/persistence/
```

**Steps**

1. Implement models and migration.
2. Implement repeatable CSV seeding.
3. Implement session authentication and browser-write protections.
4. Implement conversation ownership and turn deduplication.
5. Implement draft persistence, versioning, and confirmation authorization.
6. Implement booking validation and transactional idempotency.
7. Implement routes and consistent errors.
8. Add focused tests, including rollback after failed transactions.

**Required checks / evidence**

- Backend lint/type checks.
- Tests under `api/`, `auth/`, and `persistence/`.
- AC1, AC5, AC7, AC8, AC9, AC10.

**Invariants:** P001 scope, session ownership, no unauthorized write, stable idempotency key, short transactions.

**Non-goal:** Implementing retrieval or model prompting.

**BLOCKED if:** An agent interface or shared contract change is required. Propose the change to the integrator before editing shared files.

### WP2 — Retrieval and agent orchestration

**Owner:** AI worker. **Dependencies:** WP0; use fixed interfaces/stubs until WP1 is integrated.

**Owned paths**

```text
backend/app/agent/
backend/app/retrieval/
backend/app/config/
backend/tests/agent/
backend/tests/retrieval/
backend/evals/
```

**Steps**

1. Run the DeepSeek tool-round-trip compatibility probe using a runtime key, without printing it.
2. Build row documents and source metadata.
3. Implement local embeddings and search.
4. Implement server-owned patient context.
5. Implement narrow tool schemas.
6. Implement real REST booking adapters.
7. Implement bounded controller loop.
8. Implement draft interruptions and confirmation handling.
9. Implement post-write failure recovery.
10. Add deterministic tests and live evaluation cases.

**Required checks / evidence**

- Backend lint/type checks for owned sources.
- Agent/retrieval tests.
- Recorded live tool-round-trip result.
- AC2, AC3, AC4, AC5, AC6, AC7.

**Invariants:** Model proposes; application validates. No invented patient identity, service, or booking success. No direct repository shortcut for the REST booking tools.

**Non-goal:** Adding an agent framework or embedding service.

**BLOCKED if:** Provider tool calling does not work, required model access is unavailable, or REST/state contracts differ.

### WP3 — React workbench

**Owner:** Frontend worker. **Dependencies:** WP0; develop against fixed API fixtures.

**Owned paths**

```text
frontend/
vendor/triage/
```

Backend auth logic remains WP1-owned. Any server login-template handoff must follow the exact ownership decided in WP0.

**Steps**

1. Add pinned, licensed design-system assets and lint dependencies.
2. Implement login presentation according to the agreed backend handoff.
3. Implement chat and retry behavior.
4. Implement booking summary.
5. Implement bookings list/refetch.
6. Handle session expiry.
7. Implement runtime prefix configuration.
8. Add browser test selectors and essential accessibility behavior.

**Required checks / evidence**

- `npm run lint`, `npm run typecheck`, `npm run build`.
- Strict design-system gate.
- AC8, AC9, AC11.

**Invariants:** No optimistic booking success, no raw-HTML model rendering, no build-time production secret prefix, no secret frontend environment variables.

**Non-goal:** Visual polish beyond the functional two-panel workbench.

**BLOCKED if:** Frontend requires changed API responses or authentication behavior. Use fixtures rather than modifying backend-owned files.

### WP4 — Containers and CI

**Owner:** Infrastructure worker. **Dependencies:** WP0; smoke completion requires WP1–WP3.

**Owned paths**

```text
Dockerfile
compose*.yaml
.dockerignore
.github/workflows/ci.yml
.github/CODEOWNERS
.github/pull_request_template.md
scripts/check.sh
scripts/smoke_test.py
tests/e2e/
```

**Steps**

1. Build production image with CPU-compatible dependencies.
2. Add persistence and readiness.
3. Add local and CI overrides.
4. Implement controlled generation-provider stub for smoke tests.
5. Implement the end-to-end browser test.
6. Add parallel CI jobs and aggregate gate.
7. Add tested-image artifact publication.
8. Verify public CI requires no private source checkout.
9. Ensure CI cleanup cannot target production resources.

**Required checks / evidence**

- Compose config validation and production image build.
- Browser/integration smoke against real application, API, and database.
- Successful CI run when publication is authorized.
- AC10, AC11, AC12.

**Invariants:** Test the same image that will be published; isolated volumes; no production secrets in PR CI.

**Non-goal:** Public routing or deploying an unintegrated app.

**BLOCKED if:** Production secrets are needed for PR CI, required files/interfaces are unavailable, or the test image differs from the release artifact.

### WP5 — VM and Cloudflare bootstrap

**Owner:** Infrastructure worker. **Dependencies:** WP0; can run alongside WP1–WP4, subject to one writer per worktree.

**Owned resources**

```text
new clinicpilot-demo VM
new application tunnel/hostname route
deployment credentials and VM runtime configuration
```

**Steps**

Follow sections 11–12 exactly. Record resource identities as they are created so interrupted provisioning can resume without duplicates.

**Required checks / evidence**

- Dedicated VM runs on `cerritos` with planned CPU/RAM/disk.
- Cloud-init is complete and filesystem size is correct.
- Docker and Compose work.
- Private deployment SSH works with verified host identity.
- Tunnel reaches the application network.
- Root/wrong prefix returns `404` once routing is enabled.
- Runtime credentials remain outside Git.

**Non-goal:** Reconfiguring unrelated existing guests, DNS records, proxies, or tailnet policy.

**BLOCKED if:** Provisioning, Cloudflare, or Tailscale credentials/permissions are unavailable. Do not fabricate successful setup.

### WP6 — Integration

**Owner:** Integrator. **Dependencies:** WP1–WP4.

**Owned paths:** Shared bootstrap/settings/contracts and integration fixes. Coordinate ownership before changing worker-owned source.

**Steps**

1. Wire API routes to controller.
2. Wire controller to persistent state and REST tools.
3. Wire frontend to real API.
4. Verify runtime prefix handling.
5. Run the complete local gate on a frozen tree.
6. Run live DeepSeek evaluation cases.
7. Resolve contract mismatches centrally.
8. Perform the focused independent review and bounded fix closeout.

**Required checks / evidence**

- Full local gate.
- Live-model evaluation report.
- AC1–AC12 and review closeout.

**Non-goal:** Adding bonus features during integration.

**BLOCKED if:** Any required scenario fails or a worker reports unresolved contract changes.

### WP7 — Automatic deployment

**Owner:** Infrastructure worker/integrator. **Dependencies:** WP5, WP6.

**Owned paths**

```text
.github/workflows/deploy.yml
scripts/deploy.sh
deployment sections of documentation
```

**Steps**

1. Configure GHCR publication and verify the image is the tested artifact.
2. Configure deployment environment credentials.
3. Implement trusted-main workflow guard.
4. Deploy exact tested image digest.
5. Verify production readiness.
6. Test failure rollback without deleting data.
7. Verify the public login and protected API boundary.
8. Record deployed SHA, image digest, VM ID, and redacted check results.

**Required checks / evidence**

- AC13 and AC14.
- Published digest matches deployed digest.
- Wrong prefix, unauthenticated API, and authenticated non-mutating checks behave as specified.

**Non-goal:** Building images on the VM or reconfiguring Cloudflare during every release.

**BLOCKED if:** Deployment cannot prove which tested image is running or required access is unavailable.

### WP8 — Documentation and submission verification

**Owner:** Integrator. **Dependencies:** WP6, WP7.

**Owned paths**

```text
README.md
TECH_DOC.md
AGENTS.md final corrections
```

**Steps**

1. Document clean local setup.
2. Document database initialization/reset, distinguishing destructive reset from normal restart.
3. Document model download and configuration.
4. Document architecture and state transitions.
5. Document dataset assumptions and conservative confirmation vocabulary.
6. Document CI/deployment behavior and rollback limitations.
7. Record evaluation results honestly.
8. Rehearse the required demo.
9. Confirm the public repository contains no secrets or generated patient databases.
10. Return the repository URL and demo access details through the appropriate private handoff; do not put the password/secret suffix in public docs.

**Required checks / evidence**

- AC15.
- README commands verified against a clean setup or clean disposable environment.
- TECH_DOC includes actual limitations, not unimplemented features described as completed.

**Non-goal:** Writing a second architecture that differs from the implementation.

**BLOCKED if:** Setup instructions cannot reproduce the required flow or submission publication is not authorized.

## 15. Acceptance and test matrix

| ID | Requirement | Required evidence |
| --- | --- | --- |
| AC1 | Seed all CSVs repeatably | Seed twice; unchanged seed counts; new booking retained |
| AC2 | Grounded clinic Q&A | Correct hours/policy with source IDs |
| AC3 | Appropriate symptom routing | Knee-pain query retrieves orthopedics doctor/service |
| AC4 | Unsupported-service honesty | Allergy query does not invent specialist/service |
| AC5 | Conversational draft management | Missing fields, interruption, correction tests pass |
| AC6 | Confirmation protects writes | No write before confirmation; corrected summary requires reconfirmation |
| AC7 | REST persistence and retry safety | Actual API call saves once; lost-response retry recovers same booking |
| AC8 | Browser authentication and ownership | Unauthenticated APIs rejected; foreign conversation inaccessible |
| AC9 | Fixed-patient scope | P002 cannot be requested through browser or model tools |
| AC10 | Persistent database | Restart/recreate application; booking remains |
| AC11 | Working browser flow | Login → recommend → draft → confirm → table update |
| AC12 | Reproducible CI | All required checks pass without production secrets |
| AC13 | Automatic deployment | Successful main CI deploys exact published digest |
| AC14 | Safe deployment failure | Failed candidate restores previous image; data retained |
| AC15 | Reproducible submission | Fresh setup works using README; TECH_DOC covers decisions and limitations |

### Mandatory negative scenarios

Include tests for:

```text
“yes, but Wednesday”
unrelated “yes” after a topic change
invalid doctor ID
unsupported doctor/treatment pairing
ambiguous “at 3”
past appointment
wrong patient ID
wrong session conversation ID
duplicate chat message ID
same message ID with different text
duplicate booking request
same booking key with conflicting details
booking POST response lost after commit
provider failure after successful write
wrong password
unauthenticated direct API request
incorrect public URL prefix
```

### Stable test groups

- **TEST1 — Persistence/API:** AC1, AC7, AC9, AC10; temporary SQLite, real ORM/services, injected clock.
- **TEST2 — Agent/state:** AC2–AC7; deterministic model responses and verified tool effects.
- **TEST3 — Auth/frontend/browser:** AC8, AC9, AC11; real app/session/API/database, controlled generation provider.
- **TEST4 — Packaging/CI:** AC10, AC12; production image, isolated Compose project, no production credentials.
- **TEST5 — Deployment:** AC13, AC14; trusted main candidate, image digest verification, non-mutating public probes, rollback evidence.
- **TEST6 — Setup/demo:** AC15 plus live-model representative cases; clean environment and documented walkthrough.

Do not assert exact LLM prose. Assert facts, source records, valid selected actions, state transitions, and database effects. Do not equate mocked agent tests with demonstrated live-model quality; report both separately.

### Core functional requirements

- **When** booking details are incomplete, the system **shall** request clarification without creating a booking.
- **When** the patient confirms the current valid summary, the agent **shall** call the booking API and return the persisted result.
- **When** confirmed details change, the system **shall** require confirmation again.
- **When** a successful booking request is retried with the same key, the system **shall** return the existing booking.
- **When** a booking is created, the UI **shall** fetch and display the updated database list.
- **When** the user is unauthenticated, the system **shall** deny patient-data API access.
- **When** a trusted main CI run succeeds, the deployment workflow **shall** promote its tested image rather than rebuild it.

## 16. Worker completion report

Every worker returns:

```text
Package:
Branch/worktree:
Outcome:

Files changed:
- ...

Contracts changed:
- None, or explicit proposed change

Checks run:
- command → exit status / relevant result

Acceptance evidence:
- AC ID → test or observation

Unresolved issues:
- ...

Integration notes:
- ...

Secrets/infrastructure changes:
- Names/resources only; no secret values
```

A worker must not report completion based only on “the code looks correct.” A blocked worker reports the smallest concrete dependency needed to resume and leaves unrelated work untouched.

## 17. Final execution order

```text
WP0 Foundation
    │
    ├── WP1 Backend/auth ─────┐
    ├── WP2 Agent/RAG ────────┤
    ├── WP3 Frontend ─────────┼── WP6 Integration ──┐
    ├── WP4 Containers/CI ────┘                    │
    └── WP5 VM/Cloudflare ─────────────────────────┼── WP7 Deploy
                                                  │
                                                  └── WP8 Docs/rehearsal
```

WP4 and WP5 may be scheduled on the same infrastructure worker; they are separate packages, not permission for two writers in one worktree.

### First vertical slice

Establish this early:

```text
chat → complete draft → summary → confirmation → REST write → bookings refresh
```

Then expand recommendations, interruptions, and failure cases. Container/prefix scaffolding can progress in parallel. Do not expose functional patient-data routes before authentication is active.

### Time budget

The user has approximately 6–10 focused hours. This scope is aggressive and assumes parallel workers and existing infrastructure access. Do not spend hours rebuilding mature local tooling before the application works.

Suggested emphasis:

- WP0/contracts: short serial foundation, approximately 30–45 minutes.
- Core app streams: approximately 3–5 hours in parallel, including meaningful tests.
- Infrastructure/CI stream: approximately 2–3 hours in parallel, with credentials available.
- Integration, review, deployment, docs, rehearsal: preserve approximately 2 hours.

These are planning estimates, not guarantees. Surface blockers early and keep documentation current during implementation.

### Delivery priority if time tightens

Preserve:

1. Required application flow.
2. Confirmation and idempotency.
3. Password protection.
4. Persistent container deployment.
5. Required CI checks.
6. Working public demo.
7. README and technical document.

Cut presentation refinements and optional developer tooling first. Do not silently omit a confirmed requirement; report the tradeoff if the remaining deadline makes delivery impossible.

## 18. External dependencies and remaining setup inputs

Architecture decisions are resolved. These execution-time inputs must be obtained or discovered without inventing values:

- Working DeepSeek API credential.
- Authorization for required Git commits, GitHub repository creation, and pushes.
- Cloudflare permission to create the application tunnel and route.
- Tailscale deployment-scoped OAuth credentials/tag policy permissions.
- An authorized SSH public key and access path for cloud-init/VM bootstrap.
- A stable VM address, discovered and reserved/configured safely.
- A generated demo secret prefix and password, kept out of Git/public logs.
- Deployment SSH key and verified host key.
- The pinned embedding-model revision and compatible dependency/action versions, resolved during WP0.

Missing credentials block only the packages that require them. Continue independent application work against stubs/local configuration while reporting the blocker. No worker may claim a public endpoint, green remote CI, successful provisioning, or successful deployment without direct evidence.
