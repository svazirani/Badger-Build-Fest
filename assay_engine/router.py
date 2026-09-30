"""Live model switching on Databricks Free Edition: Databricks runs every model, Assay decides which one answers.

For each request, in order:
  1. The cheaper model answers only if Assay has certified it for this task; otherwise the primary model does.
  2. If the chosen model is busy (HTTP 429) or returns unusable output, switch live to the next model in line.
  3. Record every decision: the models tried, why each was skipped, how long it took, and who answered.
An answer from a model that is not trusted for the task (e.g. an uncertified backup) is marked needs_review:
it is delivered, but it never acts on its own.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = ROOT / "results" / "routing-policy.json"
LOG_PATH = ROOT / "results" / "routing-log.jsonl"

NAMES = {
    "databricks-meta-llama-3-3-70b-instruct": "Llama 70B",
    "databricks-meta-llama-3-1-8b-instruct": "Llama 8B",
    "databricks-qwen3-next-80b-a3b-instruct": "Qwen 80B",
    "databricks-gpt-oss-120b": "gpt-oss 120B",
    "databricks-gpt-oss-20b": "gpt-oss 20B",
    "databricks-llama-4-maverick": "Llama 4 Maverick",
    "databricks-gemma-3-12b": "Gemma 3 12B",
    "databricks-qwen35-122b-a10b": "Qwen3.5 122B",
}


def name(model: str | None) -> str:
    return NAMES.get(model or "", model or "nobody")


def policy_from_evidence(primary: str, cheap: str, backups: list[str], *, cheap_verdict: str | None,
                         cheap_evidence: str, task: str = "jira-triage") -> dict:
    """Routing policy from Assay's verdicts. The cheap model is used only on a CERTIFY verdict."""
    return {"task": task, "primary": primary, "cheap": cheap, "backups": backups,
            "cheap_certified": cheap_verdict == "CERTIFY", "cheap_verdict": cheap_verdict or "NOT EVALUATED",
            "cheap_evidence": cheap_evidence, "trusted": [primary] + ([cheap] if cheap_verdict == "CERTIFY" else []),
            "computed_at": datetime.now(timezone.utc).isoformat()}


def policy_from_scorecard(scorecard: list[dict], current_primary: str, *, margin: float = 0.05,
                          max_unusable: float = 0.05, min_answered: int = 100, task: str = "jira-triage") -> dict:
    """The cheapest model proven good enough for this task, from graded outcomes (scripts/heavy_grade.py).

    A model may replace the current main model when it (1) answered enough tickets, (2) returns unreadable output
    at most `max_unusable` of the time, (3) is within `margin` of the main model's accuracy on checkable answers,
    and (4) is not significantly worse on the same tickets. Among those, the cheapest wins. Backups: the rest with
    at least 50% accuracy, best first; their answers are held for review. Re-run on new evidence: the policy adapts.
    """
    by = {b["model"]: b for b in scorecard}
    acc = lambda b: (b["precision"]["confirmed"] / (b["precision"]["confirmed"] + b["precision"]["contradicted"])  # noqa: E731
                     if b["precision"]["confirmed"] + b["precision"]["contradicted"] else 0.0)
    cost = lambda b: b.get("usd_per_1k_tasks") or float("inf")  # noqa: E731
    main = by[current_primary]
    reasons, ok = {}, []
    for b in scorecard:
        unusable = b["unusable"] / b["tasks"] if b["tasks"] else 1.0
        why = []
        if b["answered"] < min_answered:
            why.append(f"only {b['answered']} answers so far (needs {min_answered})")
        if unusable > max_unusable:
            why.append(f"{100 * unusable:.0f}% unreadable answers (limit {100 * max_unusable:.0f}%)")
        if b["model"] != current_primary:
            if acc(b) < acc(main) - margin:
                why.append(f"{100 * acc(b):.0f}% right vs {100 * acc(main):.0f}% for {name(current_primary)}")
            v = b.get("vs_main") or {}
            if v.get("p") is not None and v["p"] < 0.05 and v["worse"] > v["better"]:
                why.append(f"worse on the same tickets ({v['worse']} vs {v['better']})")
        reasons[b["model"]] = why
        if not why:
            ok.append(b)
    primary = min(ok, key=cost)["model"] if ok else current_primary
    backups = [b["model"] for b in sorted(scorecard, key=lambda b: -acc(b))
               if b["model"] != primary and acc(b) >= 0.5 and b["answered"] >= min_answered
               and b["unusable"] / max(b["tasks"], 1) <= 2 * max_unusable]
    cheapest = min(scorecard, key=cost)
    closest = sorted((b for b in scorecard if cost(b) < cost(by[primary]) and b["model"] != primary),
                     key=lambda b: len(reasons[b["model"]]) * 10 - acc(b))
    to_change = (f"{name(closest[0]['model'])} would take over (${cost(closest[0]):.2f} vs ${cost(by[primary]):.2f} per 1,000 "
                 f"tickets) once: {'; '.join(reasons[closest[0]['model']])} is fixed") if closest else "nothing cheaper exists"
    return {"task": task, "primary": primary, "cheap": cheapest["model"], "backups": backups,
            "cheap_certified": cheapest["model"] == primary, "cheap_verdict": "CERTIFY" if cheapest["model"] == primary else "REJECT",
            "cheap_evidence": "; ".join(reasons[cheapest["model"]]) or "proven good enough",
            "trusted": [primary], "basis": "graded outcomes (heavy evaluation), cheapest proven model wins",
            "rule": f"within {100 * margin:.0f} points of the main model's accuracy, not worse on the same tickets, "
                    f"at most {100 * max_unusable:.0f}% unreadable, at least {min_answered} answers",
            "reasons": {name(m): (r or ["meets every rule"]) for m, r in reasons.items()},
            "reasons_by_model": {m: r for m, r in reasons.items()},
            "what_would_change_it": to_change, "previous_primary": current_primary,
            "computed_at": datetime.now(timezone.utc).isoformat()}


def load_policy(path: Path = POLICY_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _outcome(err: Exception) -> str:
    s = str(err)
    if "429" in s or "REQUEST_LIMIT_EXCEEDED" in s:
        return "busy"
    if "invalid model JSON" in s or "Incomplete" in s:
        return "bad_output"
    return "error"


def route(ticket: dict, candidates: list[dict], policy: dict, *, prompt: str = "v2",
          judge_fn: Callable | None = None, retries: int = 1) -> tuple[list[dict] | None, dict]:
    """Answer one triage request with live switching. Returns (judgment rows or None, decision record)."""
    if judge_fn is None:
        from assay_triage.judge import judge as judge_fn  # noqa: PLC0415 (keeps tests free of model clients)
    order = ([policy["cheap"]] if policy.get("cheap_certified") else []) + [policy["primary"]] + list(policy["backups"])
    order = list(dict.fromkeys(order))
    steps, rows, answered = [], None, None
    for model in order:
        t0 = time.time()
        try:
            rows = judge_fn(ticket, candidates, model, "databricks", prompt, retries=retries)
            steps.append({"model": model, "outcome": "ok", "ms": round(1000 * (time.time() - t0))})
            answered = model
            break
        except Exception as e:  # noqa: BLE001  (every failure is a reason to switch, recorded below)
            steps.append({"model": model, "outcome": _outcome(e), "ms": round(1000 * (time.time() - t0)),
                          "error": str(e)[:160]})
    trusted = answered in policy.get("trusted", [])
    why = []
    if not policy.get("cheap_certified"):
        why.append(f"{name(policy['cheap'])} not certified ({policy.get('cheap_evidence', 'no evidence yet')})")
    for s in steps:
        if s["outcome"] != "ok":
            why.append(f"{name(s['model'])} {'busy' if s['outcome'] == 'busy' else 'gave unusable output' if s['outcome'] == 'bad_output' else 'failed'}")
    if answered:
        why.append(f"answered by {name(answered)}" + ("" if trusted else " (not certified for this task: held for review)"))
    else:
        why.append("every model failed: sent to a human")
    decision = {"ts": datetime.now(timezone.utc).isoformat(), "task": policy.get("task"), "ticket": ticket.get("key"),
                "prompt": prompt, "first_choice": order[0], "answered_by": answered,
                "switched": answered is not None and answered != order[0], "trusted": trusted,
                "needs_review": not trusted, "steps": steps, "reason": " → ".join(why)}
    return rows, decision


def log(decision: dict, path: Path = LOG_PATH) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(decision, ensure_ascii=False) + "\n")


ROUTING_DDL = """CREATE TABLE IF NOT EXISTS {table} (
  ts TIMESTAMP, task STRING, ticket STRING, prompt STRING, first_choice STRING, answered_by STRING,
  switched BOOLEAN, trusted BOOLEAN, needs_review BOOLEAN, reason STRING, steps STRING)
COMMENT 'Assay live model routing: every request, the models tried, and who answered.'"""


def log_delta(decisions: list[dict]) -> int:
    """Append decisions to the Delta table <catalog>.<schema>.routing_log (one INSERT for the batch)."""
    from assay_triage import dbx  # noqa: PLC0415
    if not decisions:
        return 0
    t = dbx.table("routing_log")
    dbx.sql(ROUTING_DDL.format(table=t))
    params, values = [], []
    for i, d in enumerate(decisions):
        cols = {"ts": d["ts"], "task": d["task"], "ticket": d["ticket"], "prompt": d["prompt"],
                "first_choice": d["first_choice"], "answered_by": d["answered_by"], "switched": d["switched"],
                "trusted": d["trusted"], "needs_review": d["needs_review"], "reason": d["reason"],
                "steps": json.dumps(d["steps"])}
        names = []
        for k, v in cols.items():
            p = f"{k}{i}"
            typ = "BOOLEAN" if isinstance(v, bool) else "TIMESTAMP" if k == "ts" else None
            params.append({"name": p, "value": None if v is None else (str(v).lower() if isinstance(v, bool) else str(v)),
                           "type": typ})
            names.append(f":{p}")
        values.append("(" + ", ".join(names) + ")")
    dbx.sql(f"INSERT INTO {t} (ts, task, ticket, prompt, first_choice, answered_by, switched, trusted, needs_review, "
            f"reason, steps) VALUES " + ", ".join(values), params=params)
    return len(decisions)
