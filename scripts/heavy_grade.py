"""Grade the heavy evaluation against the Apache maintainers' own record (no human or AI labels involved).

    python scripts/heavy_grade.py            # results/heavy-eval/report.json + REPORT.md
    python scripts/heavy_grade.py --delta    # also the tables heavy_scorecard, heavy_cases, heavy_calibration, heavy_router

Maintainer evidence per suggestion (ticket K -> earlier ticket C, relation R):
  confirmed     the maintainers' record says exactly this (duplicate link; parent / "incorporates" for part_of;
                any link or the same parent for related)
  contradicted  the record says otherwise: e.g. "duplicate" of a ticket in another project, of its own parent or a
                sibling, while K is linked as a duplicate of something else, or K was fixed on its own;
                "part of" C while K's parent is another ticket
  unlinked      no trace either way (maintainers miss links: 48% of duplicate closures are unlinked)
Precision is reported strict (unlinked = wrong), on decided cases only, and optimistic (unlinked = right).
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from assay_engine.bands import extra_needed  # noqa: E402
from assay_engine.bounds import lower_bound  # noqa: E402
from assay_engine.precedent import case_kind  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "heavy-eval"
RELS = ("duplicate", "part_of", "related")
FIXED = {"Fixed", "Done", "Implemented"}  # "Resolved" is too vague to prove a ticket was not a duplicate
# Databricks pay-per-token list prices, DBU per 1M tokens (input, output); databricks.com/product/pricing/foundation-model-serving, fetched 2026-09-27
DBU = {"databricks-meta-llama-3-3-70b-instruct": (7.143, 21.429), "databricks-meta-llama-3-1-8b-instruct": (2.143, 6.429),
       "databricks-llama-4-maverick": (7.143, 21.429), "databricks-gpt-oss-120b": (2.143, 8.571),
       "databricks-gpt-oss-20b": (1.000, 4.286), "databricks-qwen3-next-80b-a3b-instruct": (2.143, 17.143),
       "databricks-qwen35-122b-a10b": (3.143, 31.429), "databricks-gemma-3-12b": (2.143, 7.143)}
USD_PER_DBU = 0.07  # ASSUMPTION: serverless model serving list rate; the pricing page above does not state it
NAMES = {"databricks-meta-llama-3-3-70b-instruct": "Llama 3.3 70B", "databricks-meta-llama-3-1-8b-instruct": "Llama 3.1 8B",
         "databricks-llama-4-maverick": "Llama 4 Maverick", "databricks-gpt-oss-120b": "gpt-oss 120B",
         "databricks-gpt-oss-20b": "gpt-oss 20B", "databricks-qwen3-next-80b-a3b-instruct": "Qwen3-Next 80B",
         "databricks-qwen35-122b-a10b": "Qwen3.5 122B", "databricks-gemma-3-12b": "Gemma 3 12B"}
# kinds of case defined by the parent field, which the grader itself uses: their "proof" would be circular
STRUCTURAL = {"siblings", "candidate-is-parent"}
BINS = [(0.0, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 0.95), (0.95, 1.01)]


def load(p: Path) -> list[dict]:
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()] if p.exists() else []


class Truth:
    def __init__(self, tickets: dict, truth: list[dict]):
        self.t = tickets
        self.pair = defaultdict(set)
        self.dup_of = defaultdict(set)
        for r in truth:
            self.pair[frozenset((r["src"], r["dst"]))].add(r["relation"])
            if r["relation"] == "duplicate":
                self.dup_of[r["src"]].add(r["dst"])
                self.dup_of[r["dst"]].add(r["src"])

    def linked(self, k: str, c: str) -> set:
        return self.pair.get(frozenset((k, c)), set())

    def grade(self, k: str, c: str, rel: str) -> tuple[str, str]:
        """(confirmed | contradicted | unlinked, why in plain words)."""
        a, b = self.t[k], self.t[c]
        links = self.linked(k, c)
        proj = k.split("-")[0] != c.split("-")[0]
        parent, siblings = a.get("parent") == c, a.get("parent") and a.get("parent") == b.get("parent")
        if rel == "duplicate":
            if "duplicate" in links:
                return "confirmed", "maintainers linked them as duplicates"
            if proj:
                return "contradicted", "different Apache projects: can't be the same ticket"
            if parent:
                return "contradicted", "the earlier ticket is its parent project, not a duplicate"
            if links:
                return "contradicted", f"maintainers linked them as {'/'.join(sorted(links))}, not duplicates"
            if a.get("resolution") == "Duplicate" and self.dup_of[k] - {c}:  # link direction varies: use its own closure
                return "contradicted", f"maintainers marked it a duplicate of {sorted(self.dup_of[k] - {c})[0]} instead"
            if siblings:
                return "contradicted", "two separate pieces of the same parent project"
            if a.get("resolution") in FIXED:
                return "contradicted", f"it was resolved \"{a.get('resolution')}\" on its own, not closed as a duplicate"
            return "unlinked", "no maintainer record either way"
        if rel == "part_of":
            if parent or "part_of" in links:
                return "confirmed", "the earlier ticket is its parent / umbrella"
            if a.get("parent"):
                return "contradicted", f"its parent is {a['parent']}, a different ticket"
            if proj:
                return "contradicted", "different Apache projects"
            if links:
                return "contradicted", f"maintainers linked them as {'/'.join(sorted(links))}"
            return "unlinked", "no maintainer record either way"
        if links or parent or siblings or b.get("parent") == k:
            return "confirmed", "maintainers connected them (link or same parent)"
        return "unlinked", "no maintainer record either way"

    def targets(self, k: str, shortlist: list[str]) -> dict:
        """What the maintainers say about the shortlist: candidate -> relation (for recall and misses)."""
        out = {}
        for c in shortlist:
            links = self.linked(k, c)
            if "duplicate" in links:
                out[c] = "duplicate"
            elif self.t[k].get("parent") == c or "part_of" in links:
                out[c] = "part_of"
        return out


def action(judgments: list[dict]) -> dict | None:
    """Assay's deployed unit: one action per ticket = the most confident non-none judgment."""
    js = [j for j in judgments if j.get("relation") in RELS]
    if not js:
        return None
    return sorted(js, key=lambda j: (-float(j.get("confidence") or 0), j["candidate"], j["relation"]))[0]


def prec(rows: list[dict]) -> dict:
    n = len(rows)
    c = sum(r["grade"] == "confirmed" for r in rows)
    x = sum(r["grade"] == "contradicted" for r in rows)
    return {"n": n, "confirmed": c, "contradicted": x, "unlinked": n - c - x,
            "strict": c / n if n else None, "strict_lower": lower_bound(c, n, 0.05) if n else None,
            "decided": c / (c + x) if c + x else None, "optimistic": (n - x) / n if n else None}


_INPUTS: dict = {}


def inputs() -> tuple:
    """Tickets, maintainer truth, plan and raw runs, loaded once (the replay grades many subsets)."""
    if not _INPUTS:
        tickets = {t["key"]: t for t in load(ROOT / "data" / "tickets.jsonl")}
        _INPUTS.update(tickets=tickets, T=Truth(tickets, load(ROOT / "data" / "truth.jsonl")),
                       plan=json.loads((OUT / "plan.json").read_text(encoding="utf-8")),
                       raw={f.stem: load(f) for f in sorted((OUT / "runs").glob("*.jsonl"))})
    return _INPUTS["tickets"], _INPUTS["T"], _INPUTS["plan"], _INPUTS["raw"]


def grade_all(keys: set | None = None) -> dict:
    """Grade every answer; `keys` limits grading to a subset of tickets (used by the replay)."""
    tickets, T, plan, raw = inputs()
    if keys is not None:
        plan = {**plan, "jobs": [j for j in plan["jobs"] if j["key"] in keys]}
    jobs = {j["key"]: j for j in plan["jobs"]}
    shortlist = {k: [c["ticket"]["key"] for c in j["candidates"]] for k, j in jobs.items()}

    runs, first, cases = {}, {}, []
    for stem, rows in raw.items():
        latest, first_try = {}, {}
        for r in rows:  # a retried ticket: grade the last outcome, but count unusable output on the first try
            if r["key"] not in jobs:
                continue
            latest[r["key"]] = r
            first_try.setdefault(r["key"], r["status"])
        if latest:
            runs[stem], first[stem] = list(latest.values()), Counter(first_try.values())

    board, calib, by_ticket, score = [], [], defaultdict(dict), defaultdict(dict)
    for stem, recs in runs.items():
        model = recs[0]["model"]
        ok = [r for r in recs if r["status"] == "ok"]
        st = Counter(r["status"] for r in recs)
        acts = []
        for r in ok:
            a = action(r["judgments"])
            k = r["key"]
            tg = T.targets(k, shortlist[k])
            if a is None:
                by_ticket[k][model] = None
                cases.append({"model": model, "name": NAMES.get(model, model), "slice": r["slice"], "key": k,
                              "candidate": None, "relation": "none", "confidence": None, "grade": "missed" if tg else "abstained",
                              "why": (f"maintainers link it to {next(iter(tg))} as {next(iter(tg.values()))}" if tg else "nothing proposed"),
                              "kind": None, "reason": None})
                continue
            g, why = T.grade(k, a["candidate"], a["relation"])
            row = {"model": model, "name": NAMES.get(model, model), "slice": r["slice"], "key": k,
                   "candidate": a["candidate"], "relation": a["relation"], "confidence": float(a.get("confidence") or 0),
                   "grade": g, "why": why, "kind": case_kind(tickets[k], tickets[a["candidate"]]),
                   "reason": (a.get("reason") or "")[:200],
                   "key_summary": tickets[k].get("summary"), "cand_summary": tickets[a["candidate"]].get("summary")}
            acts.append(row)
            cases.append(row)
            if r["slice"] == "stream":
                score[model][k] = {"confirmed": 1, "contradicted": -1}.get(g, 0)
            by_ticket[k][model] = (a["candidate"], a["relation"])
        stream = [a for a in acts if a["slice"] == "stream"]
        dups = [r for r in ok if r["slice"] == "dups"]
        # recall on the duplicate slice: did its action name the maintainers' duplicate?
        dup_hits, dup_said = 0, Counter()
        for r in dups:
            tg = {c for c, rel in T.targets(r["key"], shortlist[r["key"]]).items() if rel == "duplicate"}
            a = action(r["judgments"])
            if a and a["candidate"] in tg and a["relation"] == "duplicate":
                dup_hits += 1
                dup_said["duplicate (right)"] += 1
            elif a and a["candidate"] in tg:
                dup_said[f"called it {a['relation']}"] += 1
            elif a:
                dup_said["picked another ticket"] += 1
            else:
                dup_said["said nothing"] += 1
        usage = [r.get("usage") or {} for r in ok]
        tin = sum(int(u.get("prompt_tokens") or 0) for u in usage)
        tout = sum(int(u.get("completion_tokens") or 0) for u in usage)
        pin, pout = DBU.get(model, (None, None))
        dbu = (tin * pin + tout * pout) / 1e6 if pin is not None else None
        ms = sorted(r["ms"] for r in ok)
        per_rel = {rel: prec([a for a in stream if a["relation"] == rel]) for rel in RELS}
        hi = [a for a in stream if a["confidence"] >= 0.95]
        auto = {}
        for rel in RELS:
            rows = [a for a in hi if a["relation"] == rel]
            c = sum(a["grade"] == "confirmed" for a in rows)
            low = lower_bound(c, len(rows), 0.05 / 3) if rows else 0.0
            auto[rel] = {"n": len(rows), "confirmed": c, "lower": low, "acts_alone": bool(rows) and low >= 0.90,
                         "needs_more": (extra_needed(c, len(rows), 0.90, 0.05 / 3)
                                        if rows and c == len(rows) and low < 0.90 else None)}
        for lo, hi_ in BINS:
            rows = [a for a in stream if lo <= a["confidence"] < hi_ and a["grade"] != "unlinked"]
            calib.append({"model": model, "name": NAMES.get(model, model), "bin": f"{lo:.2f}-{min(hi_, 1):.2f}",
                          "n": len(rows), "confirmed": sum(a["grade"] == "confirmed" for a in rows),
                          "said": statistics.mean([a["confidence"] for a in rows]) if rows else None})
        board.append({
            "model": model, "name": NAMES.get(model, model), "tasks": len(recs), "answered": len(ok),
            "unusable": first[stem].get("bad_output", 0), "busy": st.get("busy", 0), "errors": st.get("error", 0),
            "stream_actions": len(stream), "precision": prec(stream), "by_relation": per_rel,
            "high_confidence": prec(hi), "overconfident_wrong": sum(a["grade"] == "contradicted" for a in hi),
            "acts_alone": auto,
            "dup_recall": {"n": len(dups), "hits": dup_hits, "said": dict(dup_said)},
            "latency_ms": {"p50": ms[len(ms) // 2] if ms else None, "p95": ms[int(len(ms) * 0.95)] if ms else None},
            "tokens": {"in": tin, "out": tout, "per_task": round((tin + tout) / len(ok)) if ok else None},
            "dbu": round(dbu, 4) if dbu is not None else None,
            "usd_per_1k_tasks": round(1000 * dbu * USD_PER_DBU / len(ok), 3) if dbu and ok else None,
        })

    # disagreement: tickets where the models split (the "is this really a duplicate?" cases)
    disputed = []
    for k, m in by_ticket.items():
        votes = Counter(v for v in m.values())
        if len(m) >= 5 and votes and votes.most_common(1)[0][1] <= len(m) / 2:
            top = [{"candidate": v[0], "relation": v[1], "models": n,
                    "grade": T.grade(k, v[0], v[1])[0]} if v else {"candidate": None, "relation": "none", "models": n}
                   for v, n in votes.most_common(4)]
            disputed.append({"key": k, "slice": jobs[k]["slice"], "summary": tickets[k].get("summary"),
                             "models": len(m), "options": top})

    router = {}
    for tag in ("normal", "stress"):
        routed = [d for d in load(OUT / f"routed-{tag}.jsonl") if d["ticket"] in jobs]
        if not routed:
            continue
        gr = []
        for d in routed:
            a = action(d.get("judgments") or [])
            if a:
                gr.append({"grade": T.grade(d["ticket"], a["candidate"], a["relation"])[0], "trusted": d["trusted"]})
        router[tag] = {"requests": len(routed), "switches": sum(d["switched"] for d in routed),
                       "held_for_review": sum(d["needs_review"] for d in routed),
                       "unanswered": sum(d["answered_by"] is None for d in routed),
                       "answered_by": dict(Counter(NAMES.get(d["answered_by"], "nobody") for d in routed)),
                       "busy_events": sum(s["outcome"] == "busy" for d in routed for s in d["steps"]),
                       "unusable_events": sum(s["outcome"] == "bad_output" for d in routed for s in d["steps"]),
                       "latency_ms_p50": sorted(sum(s["ms"] for s in d["steps"]) for d in routed)[len(routed) // 2],
                       "precision": prec([{"grade": g["grade"]} for g in gr]),
                       "precision_trusted": prec([{"grade": g["grade"]} for g in gr if g["trusted"]]),
                       "precision_held": prec([{"grade": g["grade"]} for g in gr if not g["trusted"]])}

    kinds = defaultdict(list)
    for c in cases:
        if c.get("kind"):  # every slice: the targeted slices exist to give rare kinds enough cases
            kinds[(c["relation"], c["kind"])].append(c)
    edge = [{"relation": r, "kind": k, **prec(v)} for (r, k), v in sorted(kinds.items(), key=lambda kv: -len(kv[1]))
            if k != "other" or len(v) >= 20]
    cross = [c for c in cases if c.get("candidate")
             and c["key"].split("-")[0] != c["candidate"].split("-")[0]]
    edge.append({"relation": "any", "kind": "cross-project", **prec(cross)})
    main = "databricks-meta-llama-3-3-70b-instruct"
    from scipy.stats import binomtest  # noqa: PLC0415
    for b in board:
        p = b["precision"]
        dec_n = p["confirmed"] + p["contradicted"]
        b["decided_lower"] = lower_bound(p["confirmed"], dec_n, 0.05) if dec_n else 0.0
        b["unusable_rate"] = b["unusable"] / b["tasks"] if b["tasks"] else 0.0
        h = b["high_confidence"]
        b["overconfident_rate"] = h["contradicted"] / h["n"] if h["n"] else 0.0
        why = []
        if b["decided_lower"] < 0.5:
            why.append(f"right on only {p['confirmed']} of {dec_n} answers the record can check")
        if b["unusable_rate"] > 0.05:
            why.append(f"{b['unusable']} of {b['tasks']} answers unreadable")
        if h["n"] >= 5 and b["overconfident_rate"] >= 0.2:
            why.append(f"said 95%+ sure and was contradicted {h['contradicted']} of {h['n']} times")
        alone = [rel for rel, v in b["acts_alone"].items() if v["acts_alone"]]
        b["verdict"] = "acts alone" if alone and not why else ("not allowed" if why else "may suggest")
        b["verdict_reason"] = ("; ".join(why) if why else
                               f"right on {p['confirmed']} of {dec_n} checkable answers (at least {100 * b['decided_lower']:.0f}%)")
        if b["model"] != main and main in score:
            common = set(score[b["model"]]) & set(score[main])
            better = sum(score[b["model"]][k] > score[main][k] for k in common)
            worse = sum(score[b["model"]][k] < score[main][k] for k in common)
            b["vs_main"] = {"tickets": len(common), "better": better, "worse": worse,
                            "p": binomtest(better, better + worse, 0.5).pvalue if better + worse else None}
    # the routing policy from this evidence: cheapest proven main model, backups by accuracy, the rest not used
    from assay_engine.router import policy_from_scorecard  # noqa: PLC0415
    policy = policy_from_scorecard(board, main) if main in {b["model"] for b in board} else None
    for b in board:
        if policy:
            b["role"] = ("main" if b["model"] == policy["primary"] else "backup" if b["model"] in policy["backups"] else "not used")
            rs = policy["reasons_by_model"].get(b["model"], [])
            b["role_reason"] = ("cheapest model that meets every rule" if b["role"] == "main" else
                                ("; ".join(rs) + ". Used only when the main model is busy; its answers wait for review")
                                if b["role"] == "backup" and rs else
                                "meets every rule; used when the main model is busy, its answers wait for review"
                                if b["role"] == "backup" else "; ".join(rs))

    # past-decision patterns rebuilt on the maintainers' record (+ the earlier audited labels), proven by leave-one-out
    from assay_engine import precedent as P  # noqa: PLC0415
    runs_dir = ROOT / "results" / "stage-2-3-runs"
    decisions = {d["id"]: d for d in P.load_decisions(sorted(runs_dir.glob("*-labels.ai.jsonl")),
                                                       [runs_dir / "spot-check-round2.jsonl"])}
    for c in cases:
        if c["grade"] in ("confirmed", "contradicted") and c.get("kind") not in STRUCTURAL:
            k = f"{c['key']}|{c['candidate']}|{c['relation']}"
            if k not in decisions or decisions[k]["source"] == "ai":
                decisions[k] = {"id": k, "key": c["key"], "candidate": c["candidate"], "relation": c["relation"],
                                "correct": c["grade"] == "confirmed", "source": "maintainer"}
    dec = list(decisions.values())
    memory = P.build_memory(dec, tickets)
    loo = P.leave_one_out(dec, tickets)
    precedents = {"decisions": len(dec), "sources": dict(Counter(d["source"] for d in dec)),
                  "memory": sorted(memory.values(), key=lambda m: -m["n"]), "leave_one_out": loo,
                  "records": dec}

    coverage = []
    def claim(what, k, n, target=0.90, alpha=0.05, unit="answers"):
        low = lower_bound(k, n, alpha) if n else 0.0
        up = 1 - lower_bound(n - k, n, alpha) if n else 1.0
        if n and low >= target:
            status = "proven"
        elif n and up < target:
            status = "disproven"
        else:
            status = "undecided"
        need = extra_needed(k, n, target, alpha) if status == "undecided" and n and k == n else None
        coverage.append({"claim": what, "k": k, "n": n, "unit": unit, "lower": round(low, 3), "upper": round(up, 3),
                         "target": target, "status": status, "needs_more": need})
    for b in board:
        for rel, v in b["acts_alone"].items():
            claim(f"{b['name']} may act alone on \"{ {'duplicate': 'same problem', 'part_of': 'part of a bigger project', 'related': 'connected'}[rel]}\" (when 95%+ sure)", v["confirmed"], v["n"], alpha=0.05 / 3)
    for m in memory.values():
        if m["kind"] != "other" and m["kind"] not in STRUCTURAL:
            said = "No" if m["answer"] == "reject" else "Yes"
            claim(f"Past answers can be reused: \"{ {'duplicate': 'same problem', 'part_of': 'part of a bigger project', 'related': 'connected'}[m['relation']]}\" for {m['kind_text']} (answer: {said})", m["agree"], m["n"])
    plain = {"duplicate": "same problem", "part_of": "part of a bigger project", "related": "connected", "any": "any link"}
    pooled = defaultdict(list)
    for c in cases:
        if c.get("candidate") and c["relation"] in RELS:
            pooled[c["relation"]].append(c)
    # the record can never contradict "connected" (nothing says two tickets are unconnected), so for it only the
    # strict count is honest: unlinked answers count as not shown to be right
    denom = lambda rel, p_: p_["n"] if rel == "related" else p_["confirmed"] + p_["contradicted"]  # noqa: E731
    for rel, rows in pooled.items():  # every kind together ("part of" can only be confirmed through the parent field)
        p_ = prec(rows)
        claim(f"\"{plain[rel]}\" suggestions are right (all models, all kinds of case"
              + (", unlinked counted as not shown" if rel == "related" else "") + ")", p_["confirmed"], denom(rel, p_))
    for e in edge:
        if e["kind"] in STRUCTURAL or e["relation"] == "part_of":
            continue
        what = P.KINDS.get(e["kind"], "tickets in different Apache projects").replace("no recognised pattern", "tickets with no special pattern")
        claim(f"\"{plain[e['relation']]}\" suggestions are right, for {what}", e["confirmed"],
              e["n"] if e["relation"] == "related" else e["confirmed"] + e["contradicted"])
    # why confident answers fail: the maintainer record's reason, grouped
    def cause(why: str) -> str:
        for key, label in (("its parent is", "Belongs to a different parent"), ("resolved", "Resolved independently"),
                           ("different Apache projects", "Different project"), ("linked them as", "Linked as another relation"),
                           ("duplicate of", "Duplicate of another ticket"), ("same parent project", "Sibling sub-tasks"),
                           ("is its parent project", "Parent, not a duplicate")):
            if key in why:
                return label
        return "Other"
    fps = [c for c in cases if (c.get("confidence") or 0) >= 0.95 and c["grade"] == "contradicted"]
    groups = defaultdict(list)
    for c in fps:
        groups[cause(c["why"])].append(c)
    fp_causes = [{"cause": k, "n": len(v), "share": len(v) / len(fps),
                  "relations": dict(Counter(c["relation"] for c in v)),
                  "models": dict(Counter(c["name"] for c in v).most_common(3)),
                  "example": {x: max(v, key=lambda c: (c["confidence"], c["key"])).get(x)
                              for x in ("name", "key", "candidate", "relation", "confidence", "why", "key_summary", "cand_summary")}}
                 for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1]))]

    examples, seen_models = [], Counter()
    for c in sorted((c for c in cases if (c.get("confidence") or 0) >= 0.95 and c["grade"] == "contradicted"),
                    key=lambda c: (c["model"], -c["confidence"], c["key"])):
        if seen_models[c["model"]] < 2:
            seen_models[c["model"]] += 1
            examples.append({k: c.get(k) for k in ("name", "key", "candidate", "relation", "confidence", "why", "reason",
                                                   "key_summary", "cand_summary", "kind")})
    return {"plan_id": plan["plan_id"], "extra_plan_id": plan.get("extra_plan_id"), "precedents": precedents,
            "policy": policy,
            "examples": examples, "fp_causes": fp_causes,
            "coverage": coverage,
            "slices": dict(Counter(j["slice"] for j in plan["jobs"])), "stream_tickets": sum(j["slice"] == "stream" for j in plan["jobs"]),
            "dup_tickets": sum(j["slice"] == "dups" for j in plan["jobs"]), "usd_per_dbu_assumed": USD_PER_DBU,
            "scorecard": board, "calibration": calib, "edge_cases": edge, "disputed": disputed[:60],
            "router": router, "cases": cases}


def pct(x):
    return "–" if x is None else f"{100 * x:.0f}%"


def markdown(rep: dict) -> str:
    L = [f"# Heavy evaluation on Databricks ({len(rep['scorecard'])} models)", "",
         f"Plan `{rep['plan_id'][:12]}`: {rep['stream_tickets']} stream tickets (precision) + {rep['dup_tickets']} "
         "maintainer-confirmed duplicates (recall, reported separately). Prompt v2. Graded only against the Apache "
         "maintainers' own record. Strict = unlinked counted wrong; decided = only cases the record settles.", "",
         "| Model | Answered | Unusable | Actions | Strict precision [95% lower] | Decided | ≥0.95 conf: strict | Confident & contradicted | Dup recall | p50 s | Tokens/task | $/1k tasks* |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for b in sorted(rep["scorecard"], key=lambda b: -(b["precision"]["strict"] or 0)):
        p, h = b["precision"], b["high_confidence"]
        L.append(f"| {b['name']} | {b['answered']}/{b['tasks']} | {b['unusable']} | {p['n']} | {pct(p['strict'])} [{pct(p['strict_lower'])}] | "
                 f"{pct(p['decided'])} | {pct(h['strict'])} (n={h['n']}) | {b['overconfident_wrong']} | "
                 f"{b['dup_recall']['hits']}/{b['dup_recall']['n']} | {(b['latency_ms']['p50'] or 0) / 1000:.1f} | "
                 f"{b['tokens']['per_task']} | {b['usd_per_1k_tasks']} |")
    L += ["", "## Assay's verdict per model", "", "| Model | Role (cheapest proven wins) | Why | Acts alone? | vs Llama 3.3 70B (same tickets) |", "|---|---|---|---|---|"]
    for b in sorted(rep["scorecard"], key=lambda b: -b["decided_lower"]):
        v = b.get("vs_main")
        L.append(f"| {b['name']} | {b.get('role', '–')} | {b.get('role_reason', b['verdict_reason'])} | "
                 f"{'yes' if b['verdict'] == 'acts alone' else 'no'} ({b['verdict_reason']}) | "
                 + (f"better on {v['better']}, worse on {v['worse']} (p={v['p']:.3g})" if v and v['p'] is not None else "–") + " |")
    L += ["", "## Coverage: does every claim reach a verdict?", "",
          "| Claim | Evidence | 95% interval | Status |", "|---|---|---|---|"]
    for c in rep["coverage"]:
        st = c["status"] + (f" (≈{c['needs_more']} more)" if c.get("needs_more") else "")
        L.append(f"| {c['claim']} | {c['k']}/{c['n']} | {100 * c['lower']:.0f}–{100 * c['upper']:.0f}% | {st} |")
    pr = rep["precedents"]
    L += ["", f"## Past-decision patterns ({pr['decisions']} decisions: {pr['sources']})", "",
          "| Relation | Kind of case | Answer | Agree | Lower | Handled automatically? |", "|---|---|---|---|---|---|"]
    for m in pr["memory"]:
        L.append(f"| {m['relation']} | {m['kind_text']} | {m['answer']} | {m['agree']}/{m['n']} | {m['lower']:.2f} | "
                 + ("yes" if m["enabled"] else f"no (≈{m['needs_more']} more)" if m["needs_more"] else "no") + " |")
    lo = pr["leave_one_out"]
    L.append(f"\nLeave-one-out: auto-resolved {lo['auto_resolved']} of {lo['decisions']}, right {lo['right']}"
             + (f" (lower bound {lo['lower_95']:.2f})" if lo['auto_resolved'] else ""))
    L += ["", f"*List price: DBU per 1M tokens from databricks.com (fetched 2026-09-27) × an ASSUMED ${rep['usd_per_dbu_assumed']}/DBU. "
          "Our actual cost on Free Edition: $0.", "", "## Live router (normal = alone; stress = alongside 32 evaluation calls)", "", "```", json.dumps(rep["router"], indent=1), "```",
          "", "## Edge cases (stream, all models pooled)", "", "| Relation | Kind of case | Actions | Confirmed | Contradicted | Unlinked |", "|---|---|---|---|---|---|"]
    for e in rep["edge_cases"]:
        L.append(f"| {e['relation']} | {e['kind']} | {e['n']} | {e['confirmed']} | {e['contradicted']} | {e['unlinked']} |")
    return "\n".join(L) + "\n"


def meta(rep: dict) -> dict:
    sc = rep["scorecard"]
    graded = [c for c in rep["cases"] if c["grade"] in ("confirmed", "contradicted")]
    hi = [c for c in rep["cases"] if (c.get("confidence") or 0) >= 0.95 and c["grade"] in ("confirmed", "contradicted")]
    return {"plan_id": rep["plan_id"], "extra_plan_id": rep.get("extra_plan_id"), "slices": rep["slices"],
            "tickets": sum(rep["slices"].values()), "models": len(sc),
            "calls": sum(b["tasks"] for b in sc), "answered": sum(b["answered"] for b in sc),
            "unusable": sum(b["unusable"] for b in sc), "actions": len([c for c in rep["cases"] if c.get("candidate")]),
            "graded": len(graded), "hi_graded": len(hi), "hi_wrong": sum(c["grade"] == "contradicted" for c in hi),
            "dbu": round(sum(b["dbu"] or 0 for b in sc), 3), "usd_per_dbu_assumed": rep["usd_per_dbu_assumed"],
            "tokens": sum(b["tokens"]["in"] + b["tokens"]["out"] for b in sc),
            "claims": {s: sum(c["status"] == s for c in rep["coverage"]) for s in ("proven", "disproven", "undecided")}}


def to_delta(rep: dict) -> None:
    from assay_triage import dbx  # noqa: PLC0415
    import importlib.util  # noqa: PLC0415
    spec = importlib.util.spec_from_file_location("sync_results", ROOT / "scripts" / "sync_results.py")
    S = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(S)
    S.SCHEMAS["heavy_scorecard"] = ("model STRING, name STRING, data STRING", "Heavy evaluation: one row per model (data is JSON)")
    S.SCHEMAS["heavy_cases"] = ("model STRING, name STRING, slice STRING, key STRING, candidate STRING, relation STRING, "
                                "confidence DOUBLE, grade STRING, why STRING, kind STRING, reason STRING, key_summary STRING, "
                                "cand_summary STRING", "Every graded agent action in the heavy evaluation")
    S.SCHEMAS["heavy_summary"] = ("name STRING, data STRING", "Heavy evaluation: calibration, edge cases, disputes, router (JSON)")
    S.write("heavy_scorecard", [{"model": b["model"], "name": b["name"], "data": b} for b in rep["scorecard"]])
    S.write("heavy_cases", rep["cases"])
    S.write("heavy_summary", [{"name": k, "data": rep[k]} for k in ("calibration", "edge_cases", "disputed", "router",
                                                                    "coverage", "examples", "policy", "fp_causes", "replay")
                             if k in rep] +
            [{"name": "precedents", "data": {k: v for k, v in rep["precedents"].items() if k != "records"}},
             {"name": "meta", "data": meta(rep)}])
    print("delta: heavy_scorecard, heavy_cases, heavy_summary")


def replay(rep: dict, step: int = 50) -> dict:
    """Snapshots every `step` tickets, in arrival order (ticket creation date): how the verdicts form over time."""
    tickets, _, plan, _ = inputs()
    order = sorted({j["key"] for j in plan["jobs"]}, key=lambda k: (tickets[k].get("created") or "", k))
    marks = list(range(step, len(order), step)) + [len(order)]
    snaps, prev = [], None
    for n in marks:
        r = grade_all(set(order[:n]))
        m = meta(r)
        models = []
        for b in r["scorecard"]:
            p, h = b["precision"], b["high_confidence"]
            models.append({"model": b["model"], "name": b["name"], "confirmed": p["confirmed"], "contradicted": p["contradicted"],
                           "hi_confirmed": h["confirmed"], "hi_contradicted": h["contradicted"], "unusable": b["unusable"],
                           "tasks": b["tasks"], "answered": b["answered"], "decided_lower": b["decided_lower"],
                           "role": b.get("role"), "usd_per_1k_tasks": b.get("usd_per_1k_tasks")})
        proven = sorted(f"{x['relation']}/{x['kind']}" for x in r["precedents"]["memory"] if x["enabled"])
        snap = {"tickets": n, "date": (tickets[order[n - 1]].get("created") or "")[:10], "meta": m, "models": models,
                "primary": (r.get("policy") or {}).get("primary"), "proven": proven,
                "loo": {k: r["precedents"]["leave_one_out"][k] for k in ("auto_resolved", "right", "decisions")},
                "router": (r.get("router") or {}).get("normal")}
        ev = []
        if prev:
            if snap["primary"] != prev["primary"]:
                ev.append(f"Primary model changes to {NAMES.get(snap['primary'], snap['primary'])}")
            roles_before = {x["model"]: x["role"] for x in prev["models"]}
            label = {"main": "primary", "backup": "a backup", "not used": "excluded"}
            for x in models:
                before = roles_before.get(x["model"])
                if before and before != x["role"] and x["role"] != "main":
                    ev.append(f"{x['name']} is now {label.get(x['role'], x['role'])}")
            plain = {"bump-same-lib-diff-version": "version upgrades", "bump-same-lib-same-version": "same-version upgrades",
                     "same-title": "identical titles", "both-test-failures": "test-failure reports"}
            for pkey in sorted(set(proven) - set(prev["proven"])):
                rel, kind = pkey.split("/")
                ev.append(f"Automated: {rel.replace('_', ' ')} on {plain.get(kind, kind)}")
            for pkey in sorted(set(prev["proven"]) - set(proven)):
                rel, kind = pkey.split("/")
                ev.append(f"Revoked after a counterexample: {rel.replace('_', ' ')} on {plain.get(kind, kind)}")
        snap["events"] = ev
        snaps.append(snap)
        prev = snap
        print(f"replay {n}/{len(order)}: {len(ev)} events", flush=True)
    return {"step": step, "order": "ticket creation date", "snapshots": snaps}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--delta", action="store_true")
    ap.add_argument("--replay", type=int, default=0, help="also compute replay snapshots every N tickets (e.g. 50)")
    a = ap.parse_args()
    rep = grade_all()
    if a.replay:
        rep["replay"] = replay(rep, a.replay)
    (OUT / "report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    (OUT / "REPORT.md").write_text(markdown(rep), encoding="utf-8")
    print(markdown(rep))
    if a.delta:
        to_delta(rep)


if __name__ == "__main__":
    main()
