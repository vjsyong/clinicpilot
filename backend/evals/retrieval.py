"""Deterministic retrieval evaluation over the real local models.

Usage (from the repository root):

    uv run --project backend python backend/evals/retrieval.py

This is not a pytest module. It builds the CSV-backed index with the pinned
Qwen3 embedder and jina cross-encoder reranker and checks expected record IDs in
the top-k results. It never calls DeepSeek and does not touch the application
database.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

CASES_PATH = Path(__file__).with_name("retrieval_cases.json")

__test__ = False


def main() -> int:
    from app.settings import Settings

    settings = Settings(
        _env_file=None,
        app_env="test",
        csv_dir=REPO_ROOT / "dkl_ai_interview_data",
    )
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]
    report = asyncio.run(_run(settings, cases))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


async def _run(settings: Any, cases: list[dict[str, Any]]) -> dict[str, Any]:
    from app.retrieval.index import build_knowledge_index

    index = build_knowledge_index(settings, None)
    await index.prewarm()
    results = []
    for case in cases:
        evidence = index.search_evidence(case["query"], limit=int(case["top_k"]))
        ids = [item.document.record_id for item in evidence]
        expected = list(case["expected"])
        passed = all(record_id in ids for record_id in expected)
        results.append(
            {
                "name": case["name"],
                "query": case["query"],
                "expected": expected,
                "returned": ids,
                "channels": [item.channels for item in evidence],
                "passed": passed,
            }
        )
    passed = sum(1 for result in results if result["passed"])
    return {
        "status": "passed" if passed == len(results) else "failed",
        "model": settings.embedding_model,
        "revision": settings.embedding_revision,
        "reranker": settings.reranker_model if settings.reranker_enabled else None,
        "reranker_revision": settings.reranker_revision if settings.reranker_enabled else None,
        "summary": {"total": len(results), "passed": passed, "failed": len(results) - passed},
        "cases": results,
    }


if __name__ == "__main__":
    raise SystemExit(main())
