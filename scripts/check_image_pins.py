#!/usr/bin/env python3
"""Fail if a Dockerfile FROM or compose `image:` line does not carry an @sha256 digest (IFORA-21).

Exempt: build-stage references (FROM <earlier stage>), images supplied through ${VAR} (docker-compose.ci.yml,
set by scripts/ci-deploy.sh) and images built locally by this repo (LOCAL_IMAGES).
Refresh a pin: see README "Image pins".
"""
import re
import subprocess
import sys
from pathlib import Path

LOCAL_IMAGES = {"ifora-ci-backend:py312"}
FROM_RE = re.compile(r"^\s*FROM\s+(?:--platform=\S+\s+)?(\S+)(?:\s+AS\s+(\S+))?", re.I)
IMAGE_RE = re.compile(r"^\s*image:\s*(\S+)")
DIGEST_RE = re.compile(r"@sha256:[0-9a-f]{64}$")


def main() -> int:
    root = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
    files = subprocess.check_output(["git", "ls-files", "docker", "demo"], text=True, cwd=root).split()
    bad = []
    for name in files:
        p = root / name
        if not (p.suffix in (".yml", ".yaml") or "Dockerfile" in p.name) or not p.is_file():
            continue
        stages: set[str] = set()
        for no, line in enumerate(p.read_text().splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            m = FROM_RE.match(line) if "Dockerfile" in p.name else IMAGE_RE.match(line)
            if not m:
                continue
            ref = m.group(1).strip("\"'")
            if "Dockerfile" in p.name and m.group(2):
                stages.add(m.group(2))
            if ref in stages or ref in LOCAL_IMAGES or "${" in ref or DIGEST_RE.search(ref):
                continue
            bad.append(f"{name}:{no}: {ref}")
    if bad:
        print("FAIL: image reference without @sha256 digest:")
        print("\n".join("  " + b for b in bad))
        return 1
    print("ok: every FROM/image: carries a sha256 digest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
