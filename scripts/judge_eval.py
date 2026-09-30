"""Judge real eval-period tickets with one or more models and grade against maintainer-made truth.

    python scripts/judge_eval.py --models haiku,sonnet --n 60 --k 5 --backend cli        # subscription, $0 extra
    python scripts/judge_eval.py --dry-run ...                                            # just show the plan

Per ticket: top-k retrieved earlier tickets; the true target is added if retrieval missed it (flagged
`injected`), so the judge's quality is measured separately from retrieval's. A pair's truth is the maintainer
relation if one exists, else "none". Caveat: maintainers miss links, so some "none" truths are real relations.
Appends to data/judgments.jsonl (resumable: finished (key, model) pairs are skipped).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from assay_triage.judge import judge  # noqa: E402
from assay_triage.judge import configuration
from assay_triage.identity import digest, resume_key
from assay_triage.retrieve import DATA, load  # noqa: E402


def plan(n: int, k: int, seed: int):
    tickets = {t["key"]: t for t in load("tickets.jsonl")}
    truth = defaultdict(dict)
    for r in load("truth.jsonl"):
        truth[r["src"]][r["dst"]] = r["relation"]
    cands = {r["key"]: r["candidates"] for r in load("candidates.jsonl")}
    rng = random.Random(seed)
    by_rel = defaultdict(list)
    for key in cands:
        rels = set(truth.get(key, {}).values())
        by_rel[next(iter(sorted(rels))) if rels else "none"].append(key)
    # stratified: equal shares of duplicate / part_of / related / none tickets
    per = max(1, n // 4)
    chosen = []
    for rel in ("duplicate", "part_of", "related", "none"):
        pool = by_rel.get(rel, [])
        chosen += rng.sample(pool, min(per, len(pool)))
    jobs = []
    for key in chosen:
        shortlist = [c["key"] for c in cands[key][:k]]
        injected = [d for d in truth.get(key, {}) if d not in shortlist and d in tickets]
        shortlist = (shortlist + injected)[: k + len(injected)]
        rng.shuffle(shortlist)
        jobs.append({"key": key, "shortlist": shortlist, "injected": injected,
                     "truth": {c: truth.get(key, {}).get(c, "none") for c in shortlist}})
    return tickets, jobs


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="haiku,sonnet")
    ap.add_argument("--backend", default="cli")
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--prompt", choices=["v1", "v2", "bad"], default="v1")
    a = ap.parse_args(argv)
    tickets, jobs = plan(a.n, a.k, a.seed)
    models = a.models.split(",")
    mix = Counter(next(iter(sorted(set(j["truth"].values()) - {"none"})), "none") for j in jobs)
    print(f"{len(jobs)} tickets x {len(models)} models = {len(jobs) * len(models)} calls; ticket mix {dict(mix)}; "
          f"{sum(len(j['shortlist']) for j in jobs)} pairs per model")
    if a.dry_run:
        return
    out = DATA / "judgments.jsonl"
    def identity(job, model):
        cfg = configuration(model, a.backend, a.prompt, len(job["shortlist"]))
        plan_id = digest({"job": job, "inputs": [tickets[job["key"]]] + [tickets[c] for c in job["shortlist"]]})
        return resume_key(job["key"], cfg["config_id"], plan_id)
    existing = load("judgments.jsonl")
    done = {}
    for r in existing:
        if r.get("run_id") and r.get("parsed"):
            done.setdefault(r["run_id"], set()).add(r["candidate"])
    todo = [(j, m) for j in jobs for m in models
            if done.get(identity(j, m), set()) != set(j["shortlist"])]

    def run(job, model):
        t = tickets[job["key"]]
        rows = judge(t, [tickets[c] for c in job["shortlist"]], model, a.backend, a.prompt)
        for r in rows:
            r["run_id"] = identity(job, model)
            r["truth"] = job["truth"][r["candidate"]]
            r["correct"] = r["relation"] == r["truth"]
            r["injected"] = r["candidate"] in job["injected"]
            r["ts"] = time.time()
        return rows

    with ThreadPoolExecutor(a.workers) as ex, open(out, "a") as f:
        futs = {ex.submit(run, j, m): (j["key"], m) for j, m in todo}
        for i, fu in enumerate(as_completed(futs), 1):
            key, m = futs[fu]
            try:
                rows = fu.result()
                f.write("".join(json.dumps(r) + "\n" for r in rows))
                f.flush()
            except Exception as ex_:  # noqa: BLE001
                print(f"  {key} {m}: {str(ex_)[:120]}", flush=True)
                if "limit" in str(ex_).lower():
                    print("usage limit reached; stopping", flush=True)
                    ex.shutdown(cancel_futures=True)
                    break
            if i % 10 == 0:
                print(f"  {i}/{len(todo)} calls done", flush=True)
    summarize()


def summarize():
    rows = load("judgments.jsonl")
    print(f"\n{len(rows)} judged pairs")
    for m in sorted({r["model"] for r in rows}):
        rs = [r for r in rows if r["model"] == m]
        acc = sum(r["correct"] for r in rs) / len(rs)
        print(f"\n[{m}] pair accuracy {acc:.1%} over {len(rs)} pairs; parse failures {sum(not r.get('parsed', True) for r in rs)}")
        for rel in ("duplicate", "part_of", "related", "none"):
            t = [r for r in rs if r["truth"] == rel]
            p = [r for r in rs if r["relation"] == rel]
            if t or p:
                rec = sum(r["correct"] for r in t) / len(t) if t else float("nan")
                prec = sum(r["correct"] for r in p) / len(p) if p else float("nan")
                print(f"   {rel:9s} recall {rec:6.1%} (n={len(t):3d})   precision {prec:6.1%} (n={len(p):3d})")
        cost = [r["cost_usd"] for r in rs if r.get("cost_usd") is not None]
        if cost:
            print(f"   list-price cost per pair ${sum(cost) / len(cost):.5f}")


if __name__ == "__main__":
    if "--summary" in sys.argv:
        summarize()
    else:
        main()
