"""Heavy evaluation on Databricks: every chat model on the same frozen tickets, plus the live router under load.

    python scripts/heavy_eval.py plan                       # freeze the plan (no model calls)
    python scripts/heavy_eval.py extend                     # add targeted edge-case slices (bumps, flaky, all dups)
    python scripts/heavy_eval.py extend-stream --stream-n 500  # more of the honest stream (new seed, disjoint)
    python scripts/heavy_eval.py boost                      # booster slices for kinds of case with undecided claims
    ASSAY_ALLOW_MODEL_CALLS=1 python scripts/heavy_eval.py run    [--models a,b] [--workers 4]
    ASSAY_ALLOW_MODEL_CALLS=1 python scripts/heavy_eval.py route  [--workers 16] [--delta] [--tag stress|normal]

Two slices, never mixed:
  stream  uniform sample of the honest stream (top retrieval score >= 0.4575), disjoint from every earlier plan:
          precision is measured here.
  dups    tickets the maintainers closed as duplicates of an earlier ticket in their shortlist: recall and the
          "is this really a duplicate?" cases. Enriched on purpose, so it is reported separately.
Resumable: re-run to finish what failed. Free Edition: no per-call charge. Every failure is kept as data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from assay_triage.plans import freeze_stream  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "heavy-eval"
PLAN = OUT / "plan.json"
MODELS = ["databricks-meta-llama-3-3-70b-instruct", "databricks-meta-llama-3-1-8b-instruct",
          "databricks-qwen3-next-80b-a3b-instruct", "databricks-qwen35-122b-a10b", "databricks-gpt-oss-120b",
          "databricks-gpt-oss-20b", "databricks-llama-4-maverick", "databricks-gemma-3-12b"]
PROMPT = "v2"
_lock = threading.Lock()


def load(p: Path) -> list[dict]:
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()] if p.exists() else []


def short(model: str) -> str:
    return model.replace("databricks-", "").replace("meta-", "")


def make_plan(n_stream: int, n_dups: int) -> dict:
    tickets = load(ROOT / "data" / "tickets.jsonl")
    cands = load(ROOT / "data" / "candidates_all.jsonl")
    truth = load(ROOT / "data" / "truth.jsonl")
    used = {j["key"] for p in (ROOT / "results" / "stage-2-3-plans").glob("*.json")
            for j in json.loads(p.read_text(encoding="utf-8"))["jobs"]}
    used |= {r["ticket"] for r in load(ROOT / "results" / "routing-log.jsonl")}
    stream = freeze_stream(tickets, cands, n=n_stream, seed=71, min_score=0.4575, excluded=used)
    # dups: maintainer duplicate link from the ticket to an EARLIER ticket that retrieval shortlisted (top 5)
    by = {t["key"]: t for t in tickets}
    dup_links = {(t["src"], t["dst"]) for t in truth if t["relation"] == "duplicate"}
    taken = used | {j["key"] for j in stream["jobs"]}
    eligible = []
    for r in cands:
        k, t = r["key"], by.get(r["key"])
        if not t or t.get("created", "") < "2025-01-01" or k in taken:
            continue
        top = [c["key"] for c in r["candidates"] if by.get(c["key"]) and by[c["key"]].get("created", "") < t["created"]][:5]
        if any((k, c) in dup_links or (c, k) in dup_links for c in top):
            eligible.append(k)
    eligible.sort()
    chosen = set(random.Random(73).sample(eligible, min(n_dups, len(eligible))))
    dups = freeze_stream(tickets, [r for r in cands if r["key"] in chosen], n=len(chosen), seed=73, min_score=0.0)
    jobs = [{**j, "slice": "stream"} for j in stream["jobs"]] + [{**j, "slice": "dups"} for j in dups["jobs"]]
    plan = {"kind": "heavy-eval-plan", "prompt": PROMPT, "models": MODELS, "seeds": {"stream": 71, "dups": 73},
            "stream_rule": "top retrieval score >= 0.4575, created >= 2025-01-01, disjoint from stage-2-3 plans and routed tickets",
            "dups_rule": "maintainer duplicate link to one of the top-5 earlier shortlisted tickets (enriched: recall only)",
            "eligible_dups": len(eligible), "jobs": jobs}
    plan["plan_id"] = hashlib.sha256(json.dumps(jobs, sort_keys=True).encode()).hexdigest()
    OUT.mkdir(parents=True, exist_ok=True)
    PLAN.write_text(json.dumps(plan), encoding="utf-8")
    return plan


EXTRA = {  # targeted slices so every edge case has enough cases on its own (enriched: reported per slice)
    "bumps": dict(n=80, seed=79, min_score=0.4575, slice_pattern=r"\b(upgrade|bump|update)\b.*\d"),
    "flaky": dict(n=50, seed=83, min_score=0.4575,
                  slice_pattern=r"(flaky|\bfail(s|ed|ing|ure)?\b).*\b(test|tests|IT|suite|case)\b|\btest\w*\b.*\b(flaky|fail(s|ed|ing|ure)?)\b"),
}


def extend_plan() -> dict:
    """Add the targeted slices and the rest of the eligible duplicates; earlier jobs stay exactly as frozen."""
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    if plan.get("extra_plan_id"):
        return plan
    tickets = load(ROOT / "data" / "tickets.jsonl")
    cands = load(ROOT / "data" / "candidates_all.jsonl")
    truth = load(ROOT / "data" / "truth.jsonl")
    used = {j["key"] for p in (ROOT / "results" / "stage-2-3-plans").glob("*.json")
            for j in json.loads(p.read_text(encoding="utf-8"))["jobs"]}
    used |= {r["ticket"] for r in load(ROOT / "results" / "routing-log.jsonl")} | {j["key"] for j in plan["jobs"]}
    extra = []
    for name, kw in EXTRA.items():
        sl = freeze_stream(tickets, cands, excluded=used, **kw)
        extra += [{**j, "slice": name} for j in sl["jobs"]]
        used |= {j["key"] for j in sl["jobs"]}
    by = {t["key"]: t for t in tickets}
    dup_links = {(t["src"], t["dst"]) for t in truth if t["relation"] == "duplicate"}
    rest = []
    for r in cands:
        k, t = r["key"], by.get(r["key"])
        if not t or t.get("created", "") < "2025-01-01" or k in used:
            continue
        top = [c["key"] for c in r["candidates"] if by.get(c["key"]) and by[c["key"]].get("created", "") < t["created"]][:5]
        if any((k, c) in dup_links or (c, k) in dup_links for c in top):
            rest.append(k)
    sl = freeze_stream(tickets, [r for r in cands if r["key"] in set(rest)], n=len(rest), seed=73, min_score=0.0)
    extra += [{**j, "slice": "dups"} for j in sl["jobs"]]
    plan["jobs"] += extra
    plan["extra_plan_id"] = hashlib.sha256(json.dumps(extra, sort_keys=True).encode()).hexdigest()
    plan["extra_rules"] = {k: v["slice_pattern"] for k, v in EXTRA.items()} | {"dups": "all remaining eligible duplicates"}
    PLAN.write_text(json.dumps(plan), encoding="utf-8")
    return plan


def extend_stream(n: int, seed: int = 91) -> dict:
    """More of the honest stream (same rule as the first 300, new seed, disjoint from every earlier job)."""
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    tag = f"stream_extra_{seed}"
    if plan.get(tag):
        return plan
    tickets = load(ROOT / "data" / "tickets.jsonl")
    cands = load(ROOT / "data" / "candidates_all.jsonl")
    used = {j["key"] for p in (ROOT / "results" / "stage-2-3-plans").glob("*.json")
            for j in json.loads(p.read_text(encoding="utf-8"))["jobs"]}
    used |= {r["ticket"] for r in load(ROOT / "results" / "routing-log.jsonl")} | {j["key"] for j in plan["jobs"]}
    sl = freeze_stream(tickets, cands, n=n, seed=seed, min_score=0.4575, excluded=used)
    extra = [{**j, "slice": "stream"} for j in sl["jobs"]]
    plan["jobs"] += extra
    plan[tag] = {"n": len(extra), "from_index": len(plan["jobs"]) - len(extra),
                 "plan_id": hashlib.sha256(json.dumps(extra, sort_keys=True).encode()).hexdigest()}
    PLAN.write_text(json.dumps(plan), encoding="utf-8")
    return plan


BOOSTERS = {  # kind of case -> tickets; picked from ticket text and shortlist only (never from the answer)
    "bump-same-lib-same-version": 43, "same-title": 117, "both-test-failures": 100, "bump-same-lib-diff-version": 80}


def extend_boosters(seed: int = 97) -> dict:
    """Booster slices for kinds of case whose claims are still undecided. Enriched: never counted in precision."""
    from assay_engine.precedent import case_kind  # noqa: PLC0415
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    if plan.get("boosters"):
        return plan
    tickets = {t["key"]: t for t in load(ROOT / "data" / "tickets.jsonl")}
    cands = load(ROOT / "data" / "candidates_all.jsonl")
    used = {j["key"] for p in (ROOT / "results" / "stage-2-3-plans").glob("*.json")
            for j in json.loads(p.read_text(encoding="utf-8"))["jobs"]}
    used |= {r["ticket"] for r in load(ROOT / "results" / "routing-log.jsonl")} | {j["key"] for j in plan["jobs"]}
    by_kind = {k: [] for k in BOOSTERS}
    for r in cands:
        k, t = r["key"], tickets.get(r["key"])
        if not t or t.get("created", "") < "2025-01-01" or k in used:
            continue
        top = [c["key"] for c in r["candidates"] if c["key"] in tickets and tickets[c["key"]].get("created", "") < t["created"]][:5]
        kinds = {case_kind(t, tickets[c]) for c in top}
        for kd in BOOSTERS:  # a ticket joins the rarest matching slice only
            if kd in kinds:
                by_kind[kd].append(k)
                break
    extra, rng, info = [], random.Random(seed), {}
    for kd, n in BOOSTERS.items():
        keys = sorted(set(by_kind[kd]) - used)
        chosen = set(rng.sample(keys, min(n, len(keys))))
        used |= chosen
        sl = freeze_stream(list(tickets.values()), [r for r in cands if r["key"] in chosen], n=len(chosen), seed=seed, min_score=0.0)
        extra += [{**j, "slice": f"boost:{kd}"} for j in sl["jobs"]]
        info[kd] = {"eligible": len(keys), "chosen": len(chosen)}
    plan["jobs"] += extra
    plan["boosters"] = {"rule": "kind of case read from the ticket and its shortlist only; enriched, reported per slice",
                        "seed": seed, "from_index": len(plan["jobs"]) - len(extra), "slices": info,
                        "plan_id": hashlib.sha256(json.dumps(extra, sort_keys=True).encode()).hexdigest()}
    PLAN.write_text(json.dumps(plan), encoding="utf-8")
    return plan


def _outcome(err: Exception) -> str:
    s = str(err)
    if "429" in s or "REQUEST_LIMIT_EXCEEDED" in s:
        return "busy"
    if "invalid model JSON" in s or "Incomplete" in s:
        return "bad_output"
    return "error"


def run_model(model: str, jobs: list[dict], workers: int) -> None:
    from assay_triage.judge import judge  # noqa: PLC0415
    path = OUT / "runs" / f"{short(model)}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    done = {r["key"] for r in load(path) if r["status"] == "ok"}
    todo = [j for j in jobs if j["key"] not in done]
    if os.environ.get("HEAVY_FROM"):  # run only jobs from this index on (the extended slices)
        keep = {j["key"] for j in jobs[int(os.environ["HEAVY_FROM"]):]}
        todo = [j for j in todo if j["key"] in keep]
    if os.environ.get("HEAVY_SLICES"):  # e.g. "stream" for a slow model that can't finish every slice in time
        todo = [j for j in todo if j["slice"] in os.environ["HEAVY_SLICES"].split(",")]
    if os.environ.get("HEAVY_REVERSE") == "1":  # a second process for a slow model works from the other end
        todo.reverse()
    print(f"{short(model)}: {len(todo)} to run ({len(done)} done)", flush=True)

    def one(job):
        t0 = time.time()
        rec = {"key": job["key"], "slice": job["slice"], "model": model, "prompt": PROMPT, "ts": time.time()}
        try:
            rows = judge(job["ticket"], [c["ticket"] for c in job["candidates"]], model, "databricks", PROMPT,
                         retries=int(os.environ.get("HEAVY_RETRIES", "5")))  # 429 back-off: 1, 2, 4, 8 … s
            rec.update(status="ok", ms=round(1000 * (time.time() - t0)), usage=rows[0].get("usage") or {},
                       judgments=[{k: r[k] for k in ("candidate", "relation", "confidence", "reason")} for r in rows])
        except Exception as e:  # noqa: BLE001  (kept as data: format failures count against the model)
            rec.update(status=_outcome(e), ms=round(1000 * (time.time() - t0)), error=str(e)[:300])
        with _lock, open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec["status"]

    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(one, todo))
    print(f"{short(model)}: " + ", ".join(f"{s} {res.count(s)}" for s in sorted(set(res))), flush=True)


def route_all(jobs: list[dict], workers: int, delta: bool, tag: str) -> None:
    from assay_engine import router  # noqa: PLC0415
    policy = router.load_policy()
    path = OUT / f"routed-{tag}.jsonl"
    done = {r["ticket"] for r in load(path)}
    todo = [j for j in jobs if j["slice"] == "stream" and j["key"] not in done]
    print(f"router: {len(todo)} to route", flush=True)

    def one(job):
        rows, d = router.route(job["ticket"], [c["ticket"] for c in job["candidates"]], policy, prompt=PROMPT)
        d["judgments"] = [{k: r[k] for k in ("candidate", "relation", "confidence", "reason")} for r in rows or []]
        d["usage"] = (rows[0].get("usage") or {}) if rows else {}
        with _lock, open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
        return d

    with ThreadPoolExecutor(workers) as ex:
        ds = list(ex.map(one, todo))
    print(f"router: {sum(d['switched'] for d in ds)} switches, {sum(d['needs_review'] for d in ds)} held for review, "
          f"{sum(d['answered_by'] is None for d in ds)} unanswered", flush=True)
    if delta and ds:
        for i in range(0, len(ds), 50):
            router.log_delta([{k: v for k, v in d.items() if k not in ("judgments", "usage")} for d in ds[i:i + 50]])
        print("router: logged to routing_log", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["plan", "extend", "extend-stream", "boost", "run", "route"])
    ap.add_argument("--stream-n", type=int, default=300)
    ap.add_argument("--dups-n", type=int, default=60)
    ap.add_argument("--models", default=",".join(MODELS))
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--delta", action="store_true")
    ap.add_argument("--tag", default="normal", help="route: stress (run alongside the model runs) or normal (alone)")
    a = ap.parse_args()
    if a.cmd == "plan":
        p = make_plan(a.stream_n, a.dups_n)
        print(json.dumps({k: p[k] for k in ("plan_id", "eligible_dups")} |
                         {"stream": sum(j["slice"] == "stream" for j in p["jobs"]),
                          "dups": sum(j["slice"] == "dups" for j in p["jobs"])}))
        return
    if a.cmd == "boost":
        print(json.dumps(extend_boosters()["boosters"]))
        return
    if a.cmd == "extend-stream":
        p = extend_stream(a.stream_n, 91)
        print(json.dumps(p["stream_extra_91"]))
        return
    if a.cmd == "extend":
        p = extend_plan()
        print(json.dumps({"extra_plan_id": p["extra_plan_id"]} | dict(__import__("collections").Counter(j["slice"] for j in p["jobs"]))))
        return
    if os.environ.get("ASSAY_ALLOW_MODEL_CALLS") != "1":
        sys.exit("Set ASSAY_ALLOW_MODEL_CALLS=1 (Databricks Free Edition: no per-call charge).")
    from assay_triage import dbx  # noqa: PLC0415
    dbx.load_env()
    jobs = json.loads(PLAN.read_text(encoding="utf-8"))["jobs"]
    if a.cmd == "route":
        route_all(jobs, a.workers, a.delta, a.tag)
        return
    models = a.models.split(",")
    with ThreadPoolExecutor(len(models)) as ex:  # one thread per model; each model runs `workers` calls at once
        list(ex.map(lambda m: run_model(m, jobs, a.workers), models))
    print("all models finished", flush=True)


if __name__ == "__main__":
    main()
