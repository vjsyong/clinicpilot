# Live-model evaluation report

Run: 2026-10-22 (local, temporary SQLite database, real DeepSeek endpoint,
real booking REST API, real retrieval index).

- Model: `deepseek-flash` (DeepSeek OpenAI-compatible endpoint)
- Embedding model: `Qwen/Qwen3-Embedding-0.6B` (FastEmbed/ONNX) @
  `af95f2c416ffe9379369ad64f9113e865db6112c`
- Reranker: `jinaai/jina-reranker-v1-turbo-en` (FastEmbed/ONNX) @
  `b8c14f4e723d9e0aab4732a7b7b93741eeeb77c2`
- Runner: `uv run --project backend python backend/evals/run.py`
- Result: **8/8 cases passed, 0 failed**

| Case | Result | What it checks |
| --- | --- | --- |
| `clinic-hours` | pass | C001 hours + 24-hour policy, `clinics.csv:C001` source |
| `cancellation-policy` | pass | C002's distinct 12-hour policy, `clinics.csv:C002` source |
| `knee-routing` | pass | Paraphrased knee complaint routes to D104/T005 with source records |
| `fee-vs-price` | pass | $250 consultation fee and $230 treatment price stay separate; no invented $480 total |
| `allergy-honesty` | pass | No allergist invented; general practice offered |
| `multi-turn-booking` | pass | Complete draft + canonical summary, then one confirmed write |
| `correction-then-confirm` | pass | "Yes, but change the date..." is a correction (version >= 2), not a confirmation; later explicit confirm writes |
| `policy-interruption` | pass | Policy answer with an active draft retains the draft and creates no booking |

The runner asserts facts, source records, draft status/version, booking events,
and database effects. It does not assert generated prose. It never prints the
API key. Standard pytest tests use deterministic model fakes and do not require
network access or a live key.

## Deployed public smoke (manual VM)

The same live path was exercised through the Cloudflare tunnel on the manual VM
deployment:

- Grounded hours/policy question returned 8:00 and 24-hour facts with
  `clinics.csv:C001` among the sources.
- Live booking flow: knee consultation → D104/T005 on 2026-12-15 15:00 →
  canonical summary → `"yes"` → `booking_created` B1005; the bookings table
  then listed B1001, B1004, B1005.
- The application container was restarted; B1005 remained after restart.
- Public login was `200`, wrong prefix `404`, unprefixed API `404`, and
  prefixed unauthenticated API `401`.

## Caveats

- This is one recorded run, not a statistically meaningful quality benchmark.
- The deterministic provider stub used by browser CI is not evidence of
  live-model quality; these cases are.
- The evaluation covers representative MVP scenarios only. It does not establish
  general medical accuracy (which is out of scope) or robustness to adversarial
  prompt injection beyond the tool/state constraints encoded in the application.
- The `policy-interruption` turn did not return a new source list because the
  model answered from the immediately preceding grounded turn; the dedicated
  clinic-hours and cancellation-policy cases verify source IDs.
