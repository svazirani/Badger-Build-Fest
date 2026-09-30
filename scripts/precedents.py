"""Reuse past reviewer decisions: build the precedent memory, prove it, apply it to unreviewed proposals.

    python scripts/precedents.py                  # target 0.90 (the AUTO target used everywhere else)
    python scripts/precedents.py --target 0.85    # a looser bar, reported separately, never silently swapped in
    python scripts/precedents.py --clicks         # also count Accept/Reject clicks from the Databricks app
    python scripts/precedents.py --delta          # write the memory to workspace.assay_triage.precedents

Writes results/precedents/precedents-<target>.json. No model calls.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from assay_engine import precedent as P  # noqa: E402
from assay_engine.policy import selected_actions  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "results" / "stage-2-3-runs"
RUN_FILES = ["permission-v2", "permission-v2-cheap", "gate-v1", "gate-v2", "stress-v1", "stress-bad"]


def load(p: Path) -> list[dict]:
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def app_clicks() -> list[dict]:
    from assay_triage import dbx  # noqa: PLC0415
    rows = dbx.sql(f"SELECT payload FROM {dbx.table('actions')}")
    return [json.loads(r[0]) for r in rows]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", type=float, default=0.90)
    ap.add_argument("--clicks", action="store_true")
    ap.add_argument("--delta", action="store_true")
    a = ap.parse_args()
    tickets = {t["key"]: t for t in load(ROOT / "data" / "tickets.jsonl")}
    decisions = P.load_decisions(sorted(RUNS.glob("*-labels.ai.jsonl")), [RUNS / "spot-check-round2.jsonl"],
                                 app_clicks() if a.clicks else [])
    memory = P.build_memory(decisions, tickets, target=a.target)
    loo = P.leave_one_out(decisions, tickets, target=a.target)

    decided = {(d["key"], d["candidate"], d["relation"]) for d in decisions}
    proposals = {}
    for f in RUN_FILES:
        rows = load(RUNS / f"{f}.jsonl")
        for cfg in {r["config_id"] for r in rows}:
            for act in selected_actions(rows, cfg):
                k = (act["key"], act["candidate"], act["relation"])
                if act["relation"] != "none" and k not in decided and act["candidate"] in tickets:
                    proposals[k] = act
    outcomes = [P.resolve(tickets[k[0]], tickets[k[1]], k[2], memory) for k in proposals]
    modes = Counter(o["mode"] for o in outcomes)

    print(f"{len(decisions)} past decisions ({dict(Counter(d['source'] for d in decisions))}); target {a.target:.0%}\n")
    for key, m in sorted(memory.items(), key=lambda kv: -kv[1]["n"]):
        state = "HANDLED AUTOMATICALLY" if m["enabled"] else (f"ask a person (≈{m['needs_more']} more reviews to prove)"
                                                             if m["needs_more"] else "ask a person")
        print(f"  {m['relation']:9s} {m['kind_text'][:62]:62s} {m['answer']:6s} {m['agree']:>2}/{m['n']:<2} "
              f"lower {m['lower']:.2f}  {state}")
    print(f"\nleave-one-out: auto-resolved {loo['auto_resolved']} of {loo['decisions']} past decisions, "
          f"right {loo['right']}" + (f" (lower bound {loo['lower_95']:.2f})" if loo["auto_resolved"] else ""))
    print(f"unreviewed proposals: {len(proposals)} -> {dict(modes)}")

    out = ROOT / "results" / "precedents"
    out.mkdir(parents=True, exist_ok=True)
    report = {"target": a.target, "decisions": len(decisions),
              "sources": dict(Counter(d["source"] for d in decisions)), "memory": memory,
              "leave_one_out": loo, "unreviewed_proposals": len(proposals), "outcomes": dict(modes),
              "auto_examples": [{"ticket": k[0], "candidate": k[1], "relation": k[2], **{x: o[x] for x in ("mode", "reason")}}
                                for k, o in zip(proposals, outcomes) if o["mode"].startswith("auto-")][:10]}
    (out / f"precedents-{int(a.target * 100)}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if a.delta:
        from assay_triage import dbx  # noqa: PLC0415
        t = dbx.table("precedents")
        dbx.sql(f"CREATE OR REPLACE TABLE {t} (relation STRING, kind STRING, kind_text STRING, answer STRING, "
                f"agree INT, n INT, lower DOUBLE, target DOUBLE, enabled BOOLEAN, needs_more INT, computed_for STRING) "
                f"COMMENT 'Assay precedent memory: what reviewers decided per kind of case, and whether reuse is proven'")
        params, vals = [], []
        for i, m in enumerate(memory.values()):
            cols = [("relation", m["relation"], None), ("kind", m["kind"], None), ("kind_text", m["kind_text"], None),
                    ("answer", m["answer"], None), ("agree", m["agree"], "INT"), ("n", m["n"], "INT"),
                    ("lower", m["lower"], "DOUBLE"), ("target", m["target"], "DOUBLE"),
                    ("enabled", str(m["enabled"]).lower(), "BOOLEAN"),
                    ("needs_more", m["needs_more"], "INT"), ("computed_for", "jira-triage", None)]
            vals.append("(" + ", ".join(f":{c}{i}" for c, _, _ in cols) + ")")
            params += [{"name": f"{c}{i}", "value": None if v is None else str(v), "type": ty} for c, v, ty in cols]
        dbx.sql(f"INSERT INTO {t} VALUES " + ", ".join(vals), params=params)
        print("delta rows:", len(memory))


if __name__ == "__main__":
    main()
