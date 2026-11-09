#!/usr/bin/env python3
"""Validate docs/workato-parity/features.yaml and regenerate STATUS.md. Uses PyYAML if installed, otherwise ruby (macOS)."""
import json, os, subprocess, sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
FIELDS = ["id", "name", "category", "doc_ref", "research", "ui", "backend", "depends_on", "files", "acceptance", "tests", "priority", "status", "gaps"]
STATUS = ["verified", "implemented", "partial", "not_implemented", "blocked", "not_planned"]
RESEARCH = ["complete", "partial", "not_researched"]


def load(path):
    try:
        import yaml
        with open(path) as f:
            return yaml.safe_load(f)
    except ImportError:
        out = subprocess.run(["ruby", "-ryaml", "-rjson", "-e", "puts JSON.generate(YAML.load_file(ARGV[0]))", path], capture_output=True, text=True, check=True)
        return json.loads(out.stdout)


def main():
    data = load(os.path.join(HERE, "features.yaml"))
    feats, errors, ids = data["features"], [], set()
    for f in feats:
        missing = [k for k in FIELDS if k not in f]
        if missing:
            errors.append(f"{f.get('id')}: missing {missing}")
        if f.get("id") in ids:
            errors.append(f"duplicate id {f['id']}")
        ids.add(f.get("id"))
        if f.get("status") not in STATUS or f.get("research") not in RESEARCH:
            errors.append(f"{f.get('id')}: bad status or research value")
        for p in list(f.get("files", [])) + list(f.get("tests", [])):
            if not os.path.exists(os.path.join(ROOT, p)):
                errors.append(f"{f['id']}: path not found: {p}")
        if f.get("status") == "verified" and not f.get("tests"):
            errors.append(f"{f['id']}: verified needs tests")
    for f in feats:
        for d in f.get("depends_on", []):
            if d not in ids:
                errors.append(f"{f['id']}: unknown dependency {d}")
    if errors:
        print("\n".join(errors))
        sys.exit(1)
    by = Counter(f["status"] for f in feats)
    rs = Counter(f["research"] for f in feats)
    lines = ["# Workato parity status", "",
             f"Generated from `features.yaml` (reviewed {data['reviewed']}) by `report.py`. Do not edit by hand. Design: `docs/architecture/022-workato-parity.md`.", "",
             f"{len(feats)} features. " + ", ".join(f"{s.replace('_', ' ')}: {by.get(s, 0)}" for s in STATUS) + ".",
             f"Research: " + ", ".join(f"{k.replace('_', ' ')}: {rs.get(k, 0)}" for k in RESEARCH) + ".", "",
             "`verified` means the acceptance criteria are covered by automated tests that passed when this was last reviewed. "
             "Nothing here claims exact parity: where Workato behaviour was not read, the feature says so.", "",
             "| ID | Feature | Status | Research | Priority | Main gaps |", "|---|---|---|---|---|---|"]
    for f in feats:
        gaps = "; ".join(f["gaps"][:2]) + (" …" if len(f["gaps"]) > 2 else "")
        lines.append(f"| {f['id']} | {f['name']} | {f['status'].replace('_', ' ')} | {f['research'].replace('_', ' ')} | {f['priority']} | {gaps or '—'} |")
    ready = [f for f in feats if f["status"] in ("not_implemented", "partial") and f["priority"] == "high"
             and all(next(x for x in feats if x["id"] == d)["status"] in ("verified", "implemented", "partial") for d in f["depends_on"])]
    lines += ["", "## Next candidates (high priority, dependencies in place)", ""] + [f"- {f['id']} {f['name']}: {f['gaps'][0] if f['gaps'] else ''}" for f in ready]
    with open(os.path.join(HERE, "STATUS.md"), "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"ok: {len(feats)} features; " + ", ".join(f"{k}={v}" for k, v in by.items()))


main()
