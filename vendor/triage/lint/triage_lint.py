#!/usr/bin/env python3
"""triage-lint — measure a project against the Triage Design System.

Usage:
    python3 lint/triage_lint.py [PATH …] [options]

    --config FILE      use .triagerc.json (default: nearest one up from PATH)
    --json             machine-readable report on stdout
    --strict           warnings fail the run as well as errors
    --max-warnings N   fail when more than N warnings (implies strict above N)
    --rules A,B        only these rule IDs
    --ignore A,B       skip these rule IDs
    --classes          enable TDS010 (classes not defined by core.css)
    --list-rules       print the rule catalogue and exit

Exit codes: 0 conforms · 1 findings · 2 usage/config error.
"""
import argparse
import fnmatch
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from engine import Spec, scan_text  # noqa: E402

DEFAULT_EXT = (".css", ".scss", ".less", ".html", ".htm", ".js", ".jsx", ".ts",
               ".tsx", ".vue", ".svelte", ".astro", ".mdx", ".mjs", ".py")
DEFAULT_IGNORE = (".git", "node_modules", "vendor", "dist", "build", ".venv",
                  "venv", "__pycache__", ".next", ".turbo", "coverage")


def load_config(start):
    d = os.path.abspath(start)
    while True:
        candidate = os.path.join(d, ".triagerc.json")
        if os.path.isfile(candidate):
            with open(candidate) as fh:
                cfg = json.load(fh)
            cfg["_path"] = candidate
            return cfg
        parent = os.path.dirname(d)
        if parent == d:
            return {}
        d = parent


def walk(target, extensions, ignore_globs):
    if os.path.isfile(target):
        return [target]
    files = []
    for base, dirs, names in os.walk(target):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE]
        for name in names:
            if os.path.splitext(name)[1].lower() not in extensions:
                continue
            path = os.path.join(base, name)
            rel = os.path.relpath(path, target).replace(os.sep, "/")
            if any(fnmatch.fnmatch(rel, pat) for pat in ignore_globs):
                continue
            files.append(path)
    return sorted(files)


def severity_score(counts):
    return max(0, round(100 - (counts.get("error", 0) * 8 +
                               counts.get("warning", 0) * 2 +
                               counts.get("info", 0) * 0.5)))


def main(argv=None):
    ap = argparse.ArgumentParser(add_help=True, description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", default=["."])
    ap.add_argument("--config")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--max-warnings", type=int, default=None)
    ap.add_argument("--rules", default="")
    ap.add_argument("--ignore", default="")
    ap.add_argument("--classes", action="store_true")
    ap.add_argument("--list-rules", action="store_true")
    args = ap.parse_args(argv)

    if args.list_rules:
        with open(os.path.join(ROOT, "spec", "rules.json")) as fh:
            for r in json.load(fh)["rules"]:
                print("%s  %-7s  %s — %s" % (r["id"], r["severity"], r["name"], r["summary"]))
        return 0

    config = load_config(args.paths[0] if args.paths else ".")
    if args.config:
        with open(args.config) as fh:
            config = json.load(fh)
    overrides = {k: v for k, v in (config.get("rules") or {}).items()}
    if args.rules:
        with open(os.path.join(ROOT, "spec", "rules.json")) as fh:
            all_ids = [r["id"] for r in json.load(fh)["rules"]]
        wanted = {x.strip() for x in args.rules.split(",") if x.strip()}
        for rid in all_ids:
            if rid not in wanted:
                overrides[rid] = "off"
    if args.ignore:
        for rid in (x.strip() for x in args.ignore.split(",") if x.strip()):
            overrides[rid] = "off"
    config["rules"] = overrides
    spec = Spec(ROOT, config)
    extensions = tuple(config.get("extensions", DEFAULT_EXT))
    ignore = tuple(DEFAULT_IGNORE) + tuple(config.get("ignore", []))
    check_unknown = args.classes or config.get("checkUnknownClasses", False)

    targets = args.paths or ["."]
    files = []
    for t in targets:
        if not os.path.exists(t):
            print("path not found: %s" % t, file=sys.stderr)
            return 2
        files.extend(walk(t, extensions, ignore))
    files = sorted(set(files))
    if not files:
        print("no files matched under %s — check include extensions/ignore globs" % ", ".join(targets),
              file=sys.stderr)
        return 2

    findings = []
    for path in files:
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError as exc:
            print("cannot read %s: %s" % (path, exc), file=sys.stderr)
            return 2
        findings.extend(scan_text(path, text, spec, check_unknown=check_unknown))

    counts = {"error": 0, "warning": 0, "info": 0}
    by_rule = {}
    for f in findings:
        counts[f.severity] += 1
        by_rule.setdefault(f.rule, {"severity": f.severity, "count": 0})
        by_rule[f.rule]["count"] += 1
    score = severity_score(counts)

    if args.json:
        print(json.dumps({
            "system": "triage-design-system",
            "version": open(os.path.join(ROOT, "VERSION")).read().strip(),
            "files_scanned": len(files),
            "findings": [f.as_dict() for f in findings],
            "counts": counts,
            "by_rule": by_rule,
            "score": score,
            "config": config.get("_path", None),
        }, indent=2))
    else:
        current = None
        for f in sorted(findings, key=lambda x: (x.path, x.line, x.rule)):
            if f.path != current:
                current = f.path
                print("\n%s" % f.path)
            print("  %5d  %-7s %s  %s" % (f.line, f.severity, f.rule, f.message))
            if f.excerpt:
                print("         %s" % f.excerpt[:110])
        print("\n%s" % ("-" * 68))
        print("files: %d   errors: %d   warnings: %d   info: %d   spec score: %d/100"
              % (len(files), counts["error"], counts["warning"], counts["info"], score))
        if by_rule:
            print("rules: " + "  ".join("%s×%d" % (r, d["count"]) for r, d in sorted(by_rule.items())))

    failed = counts["error"] > 0
    if args.strict and counts["warning"] > 0:
        failed = True
    if args.max_warnings is not None and counts["warning"] > args.max_warnings:
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
