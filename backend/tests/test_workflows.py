from __future__ import annotations

import re

from app.settings import REPO_ROOT

_USES = re.compile(r"uses:\s*([^\s#]+)")
_PINNED = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}")


def test_every_workflow_action_is_sha_pinned() -> None:
    workflows = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))
    assert workflows

    for workflow in workflows:
        for number, line in enumerate(workflow.read_text(encoding="utf-8").splitlines(), 1):
            match = _USES.search(line)
            if match is None:
                continue
            assert _PINNED.fullmatch(match.group(1)), (
                f"{workflow.name}:{number} uses a mutable action reference: {match.group(1)}"
            )
