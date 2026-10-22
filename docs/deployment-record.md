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

## Not executed / blocked

- **GitHub publication and remote CI:** no GitHub repository was created and no
  commit/push was authorized in this session. `.github/workflows/ci.yml` was
  linted and the equivalent container/browser jobs were run locally against the
  packaged image, but no remote Actions run exists.
- **Automatic deployment:** `.github/workflows/deploy.yml` and
  `scripts/deploy.sh` are implemented and statically validated, but were not
  executed. They require an authorized GitHub repository, GHCR publication,
  Tailscale OAuth client credentials, a deployment-scoped tailnet tag, and an
  SSH host key secret. None were available. The VM is not joined to the tailnet.
- **Automatic rollback evidence:** no previous image existed on this fresh VM,
  so `scripts/deploy.sh` would report that it cannot restore a first deployment.
  The rollback path is implemented but has not been demonstrated on this host.
- **Branch protection / required aggregate status:** not configured (no remote
  repository).
