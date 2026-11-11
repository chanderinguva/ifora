#!/usr/bin/env python3
"""Run pip-audit and fail on any advisory that is not allow-listed.

Allow-list format (.security-allowlist), one entry per line, '|' separated, '#' starts a comment:

    PYSEC-2024-1234 | reason the risk is accepted | 2026-12-31

An entry without a reason, with a malformed date, or whose date has passed is an error: accepted risk must be
re-reviewed, never silently permanent. Only advisory IDs are matched; no secrets belong in this file.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys


def load_allowlist(path: str, today: dt.date) -> tuple[dict[str, str], list[str]]:
    allowed: dict[str, str] = {}
    errors: list[str] = []
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except FileNotFoundError:
        return allowed, errors
    for n, raw in enumerate(lines, 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 3 or not all(parts):
            errors.append(f"{path}:{n}: need 'ID | reason | YYYY-MM-DD'")
            continue
        adv_id, reason, expiry = parts
        try:
            expires = dt.date.fromisoformat(expiry)
        except ValueError:
            errors.append(f"{path}:{n}: bad expiry date {expiry!r} (use YYYY-MM-DD)")
            continue
        if expires < today:
            errors.append(f"{path}:{n}: allow-list entry for {adv_id} expired on {expiry}; re-review or remove it")
            continue
        allowed[adv_id] = reason
    return allowed, errors


def vulnerabilities(report: dict) -> list[tuple[str, str, str, list[str]]]:
    found = []
    for dep in report.get("dependencies", []):
        for vuln in dep.get("vulns", []):
            ids = [vuln.get("id", "")] + list(vuln.get("aliases", []))
            found.append((dep.get("name", "?"), dep.get("version", "?"), vuln.get("id", "?"), ids))
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--requirements", required=True)
    ap.add_argument("--allowlist", default=".security-allowlist")
    ap.add_argument("--pip-audit", default="pip-audit")
    ap.add_argument("--report", help="read a pip-audit JSON report from this file instead of running pip-audit (tests)")
    args = ap.parse_args(argv)

    allowed, errors = load_allowlist(args.allowlist, dt.date.today())

    if args.report:
        raw = open(args.report, encoding="utf-8").read()
    else:
        cmd = args.pip_audit.split() + ["-r", args.requirements, "--format", "json", "--progress-spinner", "off"]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        raw = proc.stdout
        if not raw.strip():
            print(f"pip-audit produced no JSON (exit {proc.returncode}):\n{proc.stderr.strip()}", file=sys.stderr)
            return 2
    try:
        report = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"could not parse pip-audit output: {exc}", file=sys.stderr)
        return 2

    unaccepted = []
    for name, version, vid, ids in vulnerabilities(report):
        hit = next((i for i in ids if i in allowed), None)
        if hit:
            print(f"accepted: {name} {version} {vid} ({allowed[hit]})")
        else:
            unaccepted.append((name, version, vid))

    for e in errors:
        print(f"ALLOWLIST ERROR: {e}", file=sys.stderr)
    for name, version, vid in unaccepted:
        print(f"VULNERABLE: {name} {version} {vid}", file=sys.stderr)

    if errors or unaccepted:
        print(f"pip-audit gate failed: {len(unaccepted)} unaccepted advisories, {len(errors)} allow-list errors", file=sys.stderr)
        return 1
    print("pip-audit gate passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
