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
| CI run | 39753090072 (backend, frontend, security, container, quality, publish: success) |
| Deploy run | 39753860541 (success after fixing docker-group and state ownership) |
| Deployed SHA | `f07e9422819de61ca053d2ca9f6f87a3a745e22b` |
| Published/deployed digest | `sha256:e78f80cc14d8b83aeb1937a115b07e9bf9baa1190ad35cd5759c10919648c485` |
| GHCR package | `ghcr.io/vjsyong/clinicpilot` (public) |
| Idempotence | A rerun after the successful deploy skipped the deploy steps (`already deployed`). |
| Runner | `clinicpilot-deploy-enterprise` on the existing `github-actions-runner` VM (100), labels `self-hosted, Linux, X64`; service `actions.runner.vjsyong-clinicpilot.clinicpilot-deploy-enterprise` |
| Branch protection | `main` requires the aggregate `quality` status; force pushes/deletions disabled |

The deploy workflow verifies the CI event, repository, branch, CI conclusion,
published digest, and deployed revision before touching the host. `scripts/deploy.sh`
runs migrations, updates only the application container, checks private readiness
and public routing/auth, and restores the previous image on failure. The verified
deploy left the SQLite volume intact and kept B1005.

## Deviation from the plan and remaining gaps

- **Planned Tailscale path not used.** `TS_OAUTH_CLIENT_ID`/`TS_OAUTH_SECRET`
  and a deployment tailnet tag were unavailable. Instead, the deploy job runs on
  a repository-scoped self-hosted runner on the private enterprise network and
  reaches the VM with a key-only SSH credential over the LAN. The runner receives
  the deploy key only in the protected `production` environment. The VM is not
  joined to the tailnet.
- **Automatic rollback not forced.** The rollback branch is implemented and the
  first automatic deploy had a previous manual image available, but a deliberately
  failing candidate was not deployed to demonstrate it.
- **DHCP address.** The VM currently has `192.168.1.241`; the deploy variable uses
  that address. A durable DHCP reservation or static address was not configured.
- **Node deviation.** `cerritos` lacks KVM; the VM runs on `enterprise` with the
  same 2 vCPU / 4 GB / 40 GB shape. See the VM section above.
