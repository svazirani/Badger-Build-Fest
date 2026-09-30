"""Put everything the manager dashboard shows into Unity Catalog tables (no model calls).

    python scripts/sync_results.py            # build + write the tables below
    python scripts/sync_results.py --dry-run  # build and print counts only

Tables in <catalog>.<schema>:
  proposals       open suggestions from the main agent (Llama 70B runs) that no reviewer has answered yet
  past_decisions  every reviewed suggestion (human spot check > maintainer link > audited AI label), with its kind of case
  verdicts        Assay's verdicts in plain words (cheap model, corrections, permission) + headline counts
  stream          fresh tickets the agent has not seen, with their top-5 earlier tickets (for "Check new tickets")
The dashboard's live tables (actions, routing_log, live_proposals) are written by the app and scripts, not here.
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
from assay_engine.router import NAMES  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "results" / "stage-2-3-runs"
MAIN_RUNS = ["permission-v2", "gate-v1", "gate-v2", "stress-v1"]  # Llama 70B with the instructions in use
HELD_RUNS = {"permission-v2-cheap": "cheap-model", "stress-bad": "bad-rule"}  # never reach the inbox
STREAM_MIN_SCORE = 0.4575
MAIN_MODEL = "databricks-meta-llama-3-3-70b-instruct"


def load(p: Path) -> list[dict]:
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def pair(tickets: dict, key: str, cand: str) -> dict:
    a, b = tickets[key], tickets[cand]
    return {"key_summary": a.get("summary"), "key_created": (a.get("created") or "")[:10], "key_parent": a.get("parent"),
            "cand_summary": b.get("summary"), "cand_created": (b.get("created") or "")[:10], "cand_parent": b.get("parent"),
            "kind": P.case_kind(a, b)}


def actions_of(run: str, tickets: dict) -> list[dict]:
    rows = load(RUNS / f"{run}.jsonl")
    raw = {(r["key"], r.get("candidate"), r["relation"], r["config_id"]): r for r in rows}
    out = []
    for cfg in sorted({r["config_id"] for r in rows}):
        for a in selected_actions(rows, cfg):
            if a["relation"] == "none" or a.get("candidate") not in tickets or a["key"] not in tickets:
                continue
            r = raw.get((a["key"], a["candidate"], a["relation"], cfg), {})
            out.append({**a, "run": run, "model": r.get("model"), "reason": r.get("reason"), "prompt": r.get("prompt")})
    return out


def build(tickets: dict) -> dict:
    decisions = P.load_decisions(sorted(RUNS.glob("*-labels.ai.jsonl")), [RUNS / "spot-check-round2.jsonl"])
    decided = {(d["key"], d["candidate"], d["relation"]) for d in decisions}

    past = [{"id": d["id"], "key": d["key"], "candidate": d["candidate"], "relation": d["relation"],
             "correct": d["correct"], "source": d["source"], **pair(tickets, d["key"], d["candidate"])}
            for d in decisions if d["key"] in tickets and d["candidate"] in tickets]

    proposals: dict[tuple, dict] = {}
    main_keys, main_suggestions = set(), set()
    for run in MAIN_RUNS:
        main_keys |= {r["key"] for r in load(RUNS / f"{run}.jsonl")}
        for a in actions_of(run, tickets):
            k = (a["key"], a["candidate"], a["relation"])
            main_suggestions.add(k)
            if k in decided:
                continue
            p = proposals.setdefault(k, {"id": "|".join(k), "key": k[0], "candidate": k[1], "relation": k[2],
                                         "confidence": 0.0, "model": NAMES.get(a["model"], a["model"]),
                                         "reason": a.get("reason"), "runs": [], "origin": "stage-2-3",
                                         **pair(tickets, k[0], k[1])})
            p["runs"].append(run)
            if (a.get("confidence") or 0) > p["confidence"]:
                p["confidence"], p["reason"] = a.get("confidence") or 0.0, a.get("reason") or p["reason"]

    # examples of what the held-back configurations got WRONG (checked labels only)
    wrong = {(d["key"], d["candidate"], d["relation"]) for d in decisions if not d["correct"]}
    held_examples = {}
    for run, what in HELD_RUNS.items():
        acts = [a for a in actions_of(run, tickets) if a["relation"] == "duplicate"
                and (a["key"], a["candidate"], a["relation"]) in wrong
                and (what != "cheap-model" or (a.get("confidence") or 0) >= 0.95)]
        held_examples[what] = [{"key": a["key"], "candidate": a["candidate"], "relation": a["relation"],
                                **pair(tickets, a["key"], a["candidate"])} for a in acts[:3]]

    receipts = RUNS / "receipts-ai"
    p70 = json.loads((receipts / "llama70b" / "permission-latest.json").read_text())
    p8 = json.loads((receipts / "llama8b" / "permission-latest.json").read_text())
    bad = json.loads((receipts / "gate-v1-to-bad-latest.json").read_text())
    v2 = json.loads((receipts / "gate-v1-to-v2-latest.json").read_text())
    policy = json.loads((ROOT / "results" / "routing-policy.json").read_text())
    by_rel = lambda rec: {d["relation"]: d for d in rec["decisions"]}  # noqa: E731
    d8 = by_rel(p8)["duplicate"]
    cheap_rows = load(RUNS / "permission-v2-cheap.jsonl")
    cheap_fail = len(load(RUNS / "permission-v2-cheap.jsonl.failures.jsonl"))
    requests = sum(len({r["key"] for r in load(RUNS / f"{run}.jsonl")}) for run in MAIN_RUNS + list(HELD_RUNS)) + cheap_fail

    verdicts = [
        {"name": "cheap-model", "verdict": "QUIET", "data": {
            "model": "Llama 8B", "said_sure": d8["n"], "right": d8["k"], "wrong": d8["n"] - d8["k"],
            "cutoff": d8["threshold"], "unusable": cheap_fail, "tasks": len({r["key"] for r in cheap_rows}) + cheap_fail,
            "examples": held_examples["cheap-model"]}},
        {"name": "bad-rule", "verdict": bad["verdict"], "data": {
            "rule": "A ticket that upgrades or bumps a version is a duplicate of an earlier ticket that bumped a version.",
            "fixed": bad["fixed"], "broke": bad["broke"], "unchanged": bad["unchanged"], "n": bad["n_common"],
            "p": bad["p_discard"], "examples": held_examples["bad-rule"]}},
        {"name": "new-instructions", "verdict": v2["verdict"], "data": {
            "fixed": v2["fixed"], "broke": v2["broke"], "unchanged": v2["unchanged"], "n": v2["n_common"]}},
        {"name": "main-permission", "verdict": "SUGGEST", "data": {
            rel: {"n": d["n"], "right": d["k"], "needs_more": d["needs_more"], "mode": d["mode"]}
            for rel, d in by_rel(p70).items()}},
        {"name": "routing-policy", "verdict": policy["cheap_verdict"], "data": policy},
        {"name": "summary", "verdict": "", "data": {
            "tickets_read": len(main_keys), "suggestions": len(main_suggestions), "model_requests": requests,
            "past_decisions": len(past), "sources": dict(Counter(d["source"] for d in past)),
            "wrong_prevented": (d8["n"] - d8["k"]) + bad["broke"]}},
    ]

    planned = {j["key"] for p in (ROOT / "results" / "stage-2-3-plans").glob("*.json")
               for j in json.loads(p.read_text(encoding="utf-8"))["jobs"]}
    stream = [{"key": r["key"], "candidates": [c["key"] for c in r["candidates"][:5] if c["key"] in tickets],
               "top_score": r["candidates"][0]["score"]}
              for r in load(ROOT / "data" / "candidates_all.jsonl")
              if r["candidates"] and r["candidates"][0]["score"] >= STREAM_MIN_SCORE and r["key"] not in planned
              and r["key"] in tickets]
    for p in proposals.values():
        p["runs"] = ",".join(p["runs"])

    # the heavy evaluation (scripts/heavy_grade.py): maintainer-graded answers become past decisions; the main
    # model's answers the record cannot settle ("unlinked") go to the inbox, because they really need a person
    heavy = ROOT / "results" / "heavy-eval" / "report.json"
    if heavy.exists():
        rep = json.loads(heavy.read_text(encoding="utf-8"))
        have = {d["id"] for d in past} | {f"{d['key']}|{d['candidate']}|{d['relation']}" for d in past}
        for d in rep["precedents"]["records"]:
            if d["id"] not in have and d["key"] in tickets and d["candidate"] in tickets:
                past.append({"id": d["id"], "key": d["key"], "candidate": d["candidate"], "relation": d["relation"],
                             "correct": d["correct"], "source": d["source"], **pair(tickets, d["key"], d["candidate"])})
                have.add(d["id"])
        decided_ids = {f"{d['key']}|{d['candidate']}|{d['relation']}" for d in past}
        for c in rep["cases"]:
            k = (c["key"], c.get("candidate"), c["relation"])
            if (c["model"] == MAIN_MODEL and c["grade"] == "unlinked" and c.get("candidate") in tickets
                    and "|".join(k) not in decided_ids and k not in proposals):
                proposals[k] = {"id": "|".join(k), "key": k[0], "candidate": k[1], "relation": k[2],
                                "confidence": c["confidence"], "model": NAMES.get(MAIN_MODEL), "reason": c.get("reason"),
                                "runs": f"heavy-eval:{c['slice']}", "origin": "heavy-eval", **pair(tickets, k[0], k[1])}
    return {"proposals": list(proposals.values()), "past_decisions": past, "verdicts": verdicts, "stream": stream}


SCHEMAS = {
    "proposals": ("id STRING, key STRING, candidate STRING, relation STRING, confidence DOUBLE, model STRING, "
                  "reason STRING, runs STRING, origin STRING, key_summary STRING, key_created STRING, key_parent STRING, "
                  "cand_summary STRING, cand_created STRING, cand_parent STRING, kind STRING",
                  "Open suggestions from the main agent that no reviewer has answered yet"),
    "past_decisions": ("id STRING, key STRING, candidate STRING, relation STRING, correct BOOLEAN, source STRING, "
                       "key_summary STRING, key_created STRING, key_parent STRING, cand_summary STRING, "
                       "cand_created STRING, cand_parent STRING, kind STRING",
                       "Reviewed suggestions: human > maintainer link > audited AI label"),
    "verdicts": ("name STRING, verdict STRING, data STRING", "Assay verdicts and headline counts (data is JSON)"),
    "stream": ("key STRING, candidates STRING, top_score DOUBLE", "Fresh tickets for live agent runs (candidates: JSON)"),
}
LIVE_DDL = """CREATE TABLE IF NOT EXISTS {table} (
  id STRING, key STRING, candidate STRING, relation STRING, confidence DOUBLE, model STRING, reason STRING,
  runs STRING, origin STRING, key_summary STRING, key_created STRING, key_parent STRING, cand_summary STRING,
  cand_created STRING, cand_parent STRING, kind STRING, ts TIMESTAMP, answered_by STRING, switched BOOLEAN,
  trusted BOOLEAN, route_reason STRING)
COMMENT 'Suggestions from live agent runs started in the manager dashboard'"""


def write(name: str, rows: list[dict]) -> None:
    from assay_triage import dbx  # noqa: PLC0415
    cols_sql, comment = SCHEMAS[name]
    cols = [c.split()[0] for c in cols_sql.split(", ")]
    types = {c.split()[0]: c.split()[1] for c in cols_sql.split(", ")}
    t = dbx.table(name)
    dbx.sql(f"CREATE OR REPLACE TABLE {t} ({cols_sql}) COMMENT '{comment}'")
    for start in range(0, len(rows), 200):
        params, vals = [], []
        for i, r in enumerate(rows[start:start + 200]):
            names = []
            for c in cols:
                v = r.get(c)
                if isinstance(v, (dict, list)):
                    v = json.dumps(v)
                elif isinstance(v, bool):
                    v = str(v).lower()
                params.append({"name": f"{c}{i}", "value": None if v is None else str(v),
                               "type": {"DOUBLE": "DOUBLE", "BOOLEAN": "BOOLEAN"}.get(types[c])})
                names.append(f":{c}{i}")
            vals.append("(" + ", ".join(names) + ")")
        dbx.sql(f"INSERT INTO {t} VALUES " + ", ".join(vals), params=params)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    tickets = {t["key"]: t for t in load(ROOT / "data" / "tickets.jsonl")}
    tables = build(tickets)
    for name, rows in tables.items():
        print(f"{name:15s} {len(rows)} rows")
    print("summary:", json.dumps(next(v for v in tables["verdicts"] if v["name"] == "summary")["data"]))
    if a.dry_run:
        return
    from assay_triage import dbx  # noqa: PLC0415
    for name, rows in tables.items():
        write(name, rows)
        print("wrote", dbx.table(name), flush=True)
    dbx.sql(LIVE_DDL.format(table=dbx.table("live_proposals")))
    print("ensured", dbx.table("live_proposals"))


if __name__ == "__main__":
    main()
