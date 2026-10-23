#!/usr/bin/env python3
"""Classify changed paths into CI domains.

The CI workflow uses these booleans to skip domains whose inputs did not
change. Test-only changes run their own domain but not the container image;
documentation-only changes run no heavy jobs. If git cannot resolve the diff,
the script fails open (all domains true) so a CI configuration problem cannot
silently skip validation.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

DOMAINS = ("backend", "frontend", "security", "container")
_DOC_PREFIXES = ("docs/", "implementation_plans/")
_CONTAINER_EXCLUDES = ("backend/tests/", "backend/evals/", "frontend/tests/")
_CONTAINER_FILES = {
    "Dockerfile",
    ".dockerignore",
    "compose.yaml",
    "compose.ci.yaml",
    "package.json",
    "package-lock.json",
    "playwright.config.ts",
}


def is_docs(path: str) -> bool:
    return path.startswith(_DOC_PREFIXES) or path.endswith(".md")


def is_backend(path: str) -> bool:
    return path.startswith(("backend/", "dkl_ai_interview_data/"))


def is_frontend(path: str) -> bool:
    return path.startswith(("frontend/", "vendor/triage/"))


def is_container(path: str) -> bool:
    if path.startswith(_CONTAINER_EXCLUDES):
        return False
    if path in _CONTAINER_FILES:
        return True
    if path.startswith(
        ("backend/", "frontend/", "vendor/triage/", "dkl_ai_interview_data/")
    ):
        return True
    if path.startswith(("compose.", "tests/e2e/")):
        return True
    return path in {
        "scripts/smoke_test.py",
        ".github/workflows/ci.yml",
        ".github/workflows/deploy.yml",
    }


def classify(files: Iterable[str]) -> dict[str, bool]:
    paths = [path.strip() for path in files if path.strip()]
    return {
        "backend": any(is_backend(path) for path in paths),
        "frontend": any(is_frontend(path) for path in paths),
        # Gitleaks and dependency audits cover tests, workflow, and config too.
        "security": any(not is_docs(path) for path in paths),
        "container": any(is_container(path) for path in paths),
    }


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        check=False,
        text=True,
        capture_output=True,
    )


def _diff(base: str, head: str) -> list[str] | None:
    if not base or not head:
        return None
    check = _git("cat-file", "-e", f"{base}^{{commit}}")
    if check.returncode != 0:
        return None
    result = _git(
        "diff",
        "--name-only",
        "--no-renames",
        "--diff-filter=ACDMRTUXB",
        base,
        head,
    )
    if result.returncode != 0:
        return None
    return [line for line in result.stdout.splitlines() if line.strip()]


def _all_tracked() -> list[str]:
    result = _git("ls-files")
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git ls-files failed")
    return [line for line in result.stdout.splitlines() if line.strip()]


def changed_files(event: str, env: dict[str, str]) -> tuple[list[str], bool]:
    """Return (files, resolved). ``resolved=False`` means all-domain fallback."""
    if event == "pull_request":
        files = _diff(env.get("BASE_SHA", ""), env.get("HEAD_SHA", ""))
        if files is not None:
            return files, True
    elif event == "push":
        before = env.get("BEFORE_SHA", "")
        after = env.get("CURRENT_SHA", "")
        if before and set(before) != {"0"}:
            files = _diff(before, after)
            if files is not None:
                return files, True
    return _all_tracked(), False


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--files",
        nargs="*",
        help="Classify these paths instead of asking git (useful for local checks).",
    )
    args = parser.parse_args(argv)

    if args.files is not None:
        files = args.files
        resolved = True
    else:
        files, resolved = changed_files(
            os.environ.get("EVENT_NAME", ""),
            os.environ,
        )

    domains = classify(files)
    if not resolved:
        # A missing/unreadable base must not silently skip validation.
        domains = {name: True for name in DOMAINS}

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as handle:
            handle.write("## CI change domains\n\n")
            handle.write(f"Resolved base diff: `{resolved}`\n\n")
            handle.writelines(
                f"- **{name}**: `{str(domains[name]).lower()}`\n" for name in DOMAINS
            )
            if files:
                handle.write("\n<details><summary>Changed files</summary>\n\n")
                handle.writelines(f"- `{path}`\n" for path in files[:100])
                if len(files) > 100:
                    handle.write(f"- …and {len(files) - 100} more\n")
                handle.write("\n</details>\n")

    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8") as handle:
            handle.writelines(
                f"{name}={str(domains[name]).lower()}\n" for name in DOMAINS
            )

    print(f"resolved={resolved} files={len(files)}")
    for name in DOMAINS:
        print(f"{name}={str(domains[name]).lower()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
