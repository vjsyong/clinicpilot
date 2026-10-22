# Deployment record (non-secret)

Recorded: 2026-10-22.

## VM

| Item | Value |
| --- | --- |
| Name | `clinicpilot-demo` |
| VM ID | 106 |
| Node | `enterprise` (deviation; see below) |
| Guest | Debian 13 (trixie), cloud-init |
| vCPU / RAM / disk | 2 / 4096 MB / 40 GB |
| Disk storage | `local-lvm` on enterprise |
| Docker / Compose | 29.9.2 / v5.6.1 |
| User | `clinicpilot` (SSH key, passwordless sudo for bootstrap) |
| Runtime directory | `/opt/clinicpilot` |
| Database | SQLite in the Compose named volume `clinicpilot_data` |
| Application image | `clinicpilot:demo` (the locally tested image; see digest in `/opt/clinicpilot/state/deployed-digest`) |
| Image note | Final deployed image digest prefix `sha256:cf921f731aab`; local and VM copies of the key source files hash identically. The first runtime image omitted `vendor/triage`, so login assets 404'd. The Dockerfile now copies it; the fixed image was retagged and redeployed, and the assets return 200. |

**Node deviation:** the plan targeted `cerritos`. `cerritos` has no
`/dev/kvm` and no VMX/SVM CPU flags, so QEMU refused to start the cloned VM
there. The stopped clone was migrated back to `enterprise`, which has KVM and
sufficient capacity, and given `cpu: host` so NumPy's x86-64-v2 baseline is
available. The VM identity (106, `clinicpilot-demo`, 2 vCPU/4 GB/40 GB) is
otherwise unchanged. The QEMU guest agent was verified, cloud-init completed,
and the root filesystem shows 40 GB.

## Tunnel and DNS

| Item | Value |
| --- | --- |
| Tunnel name | `clinicpilot-demo` |
| Tunnel ID | `6f030ae7-1720-4216-bcaa-8deedb028147` |
| Public hostname | `dk.seanyong.xyz` |
| DNS | CNAME to the tunnel (Cloudflare) |
| Connector | `cloudflared` Compose service, token from runtime `.env` |
| Ingress | `cloudflared tunnel run --url http://app:8000`; the application enforces the prefix and returns 404 outside it |

The runtime prefix, password, password hash, internal tool key, DeepSeek API key,
and tunnel token live only in `/opt/clinicpilot/.env` (mode 600) and the local
private handoff file. They are not in Git or this document.

## Verification performed

- Public login page: `200`; wrong prefix: `404` JSON `not_found`; unprefixed
  API: `404`; prefixed unauthenticated API: `401` JSON `unauthorized`.
- Public login with the demo password: `303`, session cookie scoped to the
  prefix.
- Public `GET /api/bookings`: `200` with the seeded P001 rows.
- Live DeepSeek public question ("opening hours and cancellation policy for
  Metro Care Health Clinic"): correct 8:00/24-hour facts with
  `clinics.csv:C001` among the source records.
- Live public booking flow: knee consultation → D104/T005, 2026-12-15 15:00 →
  canonical summary → `"yes"` → `booking_created` B1005 persisted; the table
  then listed B1001, B1004, B1005.
- Application container restart: readiness returned, and B1005 was still in
  the bookings list (persistent named volume).
- Runtime image contains the vendored Triage assets used by the login page
  (after the missing-vendor-copy defect was found and fixed); the public
  `base.css`, `tokens.css`, and `geist.woff2` return 200.
- Public browser check: login → workbench → 3 booking rows including B1001 and
  B1005 → logout returned to the login page.
- Clean disposable setup: copied the tree without `.git`, `.venv`, `node_modules`,
  or `data`; ran the README sync, migration, seed, frontend build, and server
  commands; readiness, login page, and wrong-prefix behavior were correct.
- Local quality evidence: 119 backend tests, 4 browser tests (functional +
  restart persistence), 8/8 live eval cases, strict Triage lint 100/100,
  pip-audit/npm audit clean, and Gitleaks found no leaks.

## Automatic delivery (verified)

| Item | Value |
| --- | --- |
| Public repository | https://github.com/vjsyong/clinicpilot |
| CI run | 39765211059 (backend, frontend, security, container, quality, publish: success) |
| Deploy run | 39765963762 (success; promoted the exact tested digest) |
| Deployed SHA | `300963ec2ac5fe28d5f84c8c6f21e8986cac59bf` |
| Published/deployed digest | `sha256:987fd915472eb23082d783cb200993d0e826d3384bbb2713aa3031a4db2c4e97` |
| GHCR package | `ghcr.io/vjsyong/clinicpilot` (public) |
| Idempotence | A rerun after the successful deploy skipped the deploy steps (`already deployed`). |
| Runner | `clinicpilot-deploy-enterprise` on the existing `github-actions-runner` VM (100), labels `self-hosted, Linux, X64`; service `actions.runner.vjsyong-clinicpilot.clinicpilot-deploy-enterprise`; the runner is a tailnet member |
| Deployment transport | Tailscale MagicDNS `clinicpilot-demo.bigscale-snapper.ts.net` (100.99.97.25) with key-only SSH; `DEPLOY_HOST` is the MagicDNS name |
| Branch protection | `main` requires the aggregate `quality` status; force pushes/deletions disabled |
| Rollback drill | Pre-tab-fix drill: forced post-deploy health failure with `CLINICPILOT_HEALTH_TIMEOUT=0` and a second valid image (`...:rollback-test`, digest `sha256:48621cca...`). `deploy.sh` recreated the application with the then-previous digest `sha256:e78f80cc...`, readiness returned `200`, and B1005 remained. The drill candidate was valid; the failure was forced at the readiness gate. |

The deploy workflow verifies the CI event, repository, branch, CI conclusion,
published digest, and deployed revision before touching the host. `scripts/deploy.sh`
runs migrations, updates only the application container, checks private readiness
and public routing/auth, and restores the previous image on failure. The verified
deploy left the SQLite volume intact and kept B1005.

## Deviation from the plan and remaining gaps

- **Runner model deviation.** `TS_OAUTH_CLIENT_ID`/`TS_OAUTH_SECRET` for an
  ephemeral GitHub-hosted runner were unavailable. Instead, the deploy job runs
  on a repository-scoped self-hosted runner that is already a tailnet member and
  reaches the VM over Tailscale MagicDNS with key-only SSH. The runner receives
  the deploy key only in the protected `production` environment. The transport is
  Tailscale + SSH as planned; only the runner membership model differs.
- **Automatic rollback evidence is a forced-failure drill.** The rollback branch
  was exercised with a valid candidate and a zero-second readiness timeout, not a
  naturally broken application build. It restored the previous digest and kept
  the database volume.
- **LAN address is DHCP.** The VM's LAN address (`192.168.1.241`) may change, but
  deployment and checks use Tailscale MagicDNS, so this does not affect delivery.
- **Node deviation.** `cerritos` lacks KVM; the VM runs on `enterprise` with the
  same 2 vCPU / 4 GB / 40 GB shape. See the VM section above.

## Audit remediation deployment (2026-10-22)

The implementation audit of revision `bfbd438` found eight issues. They were
fixed, validated, and deployed from revision
`300963ec2ac5fe28d5f84c8c6f21e8986cac59bf` (digest
`sha256:987fd915472eb23082d783cb200993d0e826d3384bbb2713aa3031a4db2c4e97`).

- CI run 39765211059 passed all required jobs (backend, frontend, security,
  container, quality, publish).
- Deploy run 39765963762 promoted the tested digest to the VM.
- Public probes: login `200`, wrong prefix `404`, unauthenticated API `401`,
  `/healthz` `404`, `/readyz` `404`.
- The VM state files and running container both identify source revision
  `300963ec2ac5fe28d5f84c8c6f21e8986cac59bf` and the digest above.
- An initial push failed CI because Gitleaks flagged a deterministic non-secret
  test constant in history. The constant was replaced and a narrowly scoped
  `.gitleaksignore` fingerprint was added for the historical commit; the next
  full-history scan passed.
- The previous tab-fix deployment remains recorded here as CI run 39757644785 /
  deploy run 39758580196 at digest `sha256:8cefd033...`.

## Assistant and retrieval parity deployment (2026-10-22)

Deployed revision `1f2dde0d357dbffc4b2d89c472e0f2a67a8e2c56` (assistant/RAG
parity) from `main`.

- CI run 39772455537 passed backend, frontend, security, container, quality,
  and publish.
- Deploy run 39773302873 succeeded and promoted digest
  `sha256:cfec3f695b8489ba22462d24fac706cbf0f04cc2705781999c7523e15d97e98a`.
- The deploy step recorded `deployed sha=1f2dde0...` and the digest above.
- Public probes: login `200`, wrong prefix `404`, unauthenticated API `401`,
  `/healthz` `404`, `/readyz` `404`.
- The SQLite named volume was retained; migrations ran as the release step.
