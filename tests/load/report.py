#!/usr/bin/env python3
"""Print the k6 result files as a short table: per-step p95 and the error rate. Reads only numbers."""
import json
import sys
from pathlib import Path

for f in sorted(Path(__file__).parent.joinpath("results").glob("*.json")):
    m = json.loads(f.read_text())["metrics"]
    steps = {k[5:]: v["values"] for k, v in m.items() if k.startswith("step_")}
    it, failed, checks = m["iterations"]["values"], m["http_req_failed"]["values"], m["checks"]["values"]
    print(f"\n{f.stem}: {int(it['count'])} iterations at {it['rate']:.1f}/s, http failures {failed['rate']*100:.2f}%, checks passed {checks['rate']*100:.2f}%")
    for name, v in steps.items():
        if v.get("count", 1):
            print(f"  {name:<10} avg {v['avg']:7.1f} ms   p95 {v['p(95)']:7.1f} ms   max {v['max']:7.1f} ms")
sys.exit(0)
