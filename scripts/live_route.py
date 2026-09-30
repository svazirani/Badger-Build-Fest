"""Live model switching demo on Databricks Free Edition.

    python scripts/live_route.py --write-policy          # routing policy from Assay's verdicts (no model calls)
    python scripts/live_route.py --policy-from-eval      # cheapest proven model from the heavy evaluation (no model calls)
    python scripts/live_route.py --n 12 --workers 6      # route 12 fresh stream tickets; several at once -> real 429s
    python scripts/live_route.py --n 12 --delta          # also append the decisions to workspace.assay_triage.routing_log

Tickets come from the honest stream (top retrieval score >= 0.4575) and exclude every ticket in the Stage 2/3 plans.
Nothing is simulated: a switch happens only when a model is really busy or really returns unusable output.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from assay_engine import router  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PRIMARY, CHEAP = "databricks-meta-llama-3-3-70b-instruct", "databricks-meta-llama-3-1-8b-instruct"
BACKUPS = ["databricks-qwen3-next-80b-a3b-instruct", "databricks-gpt-oss-120b"]


def load(p: Path) -> list[dict]:
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_policy() -> dict:
    runs = ROOT / "results" / "stage-2-3-runs" / "receipts-ai"
    receipt = max((json.loads(p.read_text()) for p in runs.glob("llama8b/permission-*.json")
                   if p.name != "permission-latest.json"), key=lambda r: r["computed_at"], default=None)
    dup = next((d for d in (receipt or {}).get("decisions", []) if d["relation"] == "duplicate"), None)
    evidence = (f"right {dup['k']} of {dup['n']} when it said 95%+ sure; 11% unusable answers"
                if dup else "no evidence yet")
    policy = router.policy_from_evidence(PRIMARY, CHEAP, BACKUPS, cheap_verdict="REJECT" if dup else None,
                                         cheap_evidence=evidence)
    policy["cheap_verdict_basis"] = ("permission receipt (duplicate precision at the 0.95 cutoff) and format failures; "
                                     "no paired cost/quality comparison has been run")
    router.POLICY_PATH.write_text(json.dumps(policy, indent=2), encoding="utf-8")
    return policy


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write-policy", action="store_true")
    ap.add_argument("--policy-from-eval", action="store_true",
                    help="cheapest proven model from results/heavy-eval/report.json (no model calls)")
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--seed", type=int, default=99)
    ap.add_argument("--prompt", default="v2")
    ap.add_argument("--delta", action="store_true")
    a = ap.parse_args()
    if a.policy_from_eval:
        rep = json.loads((ROOT / "results" / "heavy-eval" / "report.json").read_text(encoding="utf-8"))
        policy = router.policy_from_scorecard(rep["scorecard"], PRIMARY)
        router.POLICY_PATH.write_text(json.dumps(policy, indent=2), encoding="utf-8")
        print(json.dumps(policy, indent=2))
        return
    if a.write_policy:
        print(json.dumps(write_policy(), indent=2))
        return
    if os.environ.get("ASSAY_ALLOW_MODEL_CALLS") != "1":
        sys.exit("Set ASSAY_ALLOW_MODEL_CALLS=1 to run (Databricks Free Edition: no per-call charge).")
    policy = router.load_policy()
    tickets = {t["key"]: t for t in load(ROOT / "data" / "tickets.jsonl")}
    planned = {j["key"] for p in (ROOT / "results" / "stage-2-3-plans").glob("*.json")
               for j in json.loads(p.read_text(encoding="utf-8"))["jobs"]}
    stream = [r for r in load(ROOT / "data" / "candidates_all.jsonl")
              if r["candidates"] and r["candidates"][0]["score"] >= 0.4575 and r["key"] not in planned]
    pick = random.Random(a.seed).sample(stream, a.n)

    def one(r):
        cands = [tickets[c["key"]] for c in r["candidates"][:5] if c["key"] in tickets]
        return router.route(tickets[r["key"]], cands, policy, prompt=a.prompt)[1]

    with ThreadPoolExecutor(a.workers) as ex:
        decisions = list(ex.map(one, pick))
    for d in decisions:
        router.log(d)
        print(f"{d['ticket']:12s} {router.name(d['answered_by']):12s} {'SWITCHED ' if d['switched'] else '         '}"
              f"{'review ' if d['needs_review'] else 'ok     '} {d['reason']}")
    c = Counter(router.name(d["answered_by"]) for d in decisions)
    busy = sum(s["outcome"] == "busy" for d in decisions for s in d["steps"])
    bad = sum(s["outcome"] == "bad_output" for d in decisions for s in d["steps"])
    print(json.dumps({"requests": len(decisions), "answered_by": c, "live_switches": sum(d["switched"] for d in decisions),
                      "busy_events": busy, "unusable_outputs": bad, "held_for_review": sum(d["needs_review"] for d in decisions)}))
    if a.delta:
        print("delta rows:", router.log_delta(decisions))


if __name__ == "__main__":
    main()
