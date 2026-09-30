"""Reuse past reviewer decisions, but only where the record proves the reuse would have been right.

Every reviewed proposal (a human click, an audited AI label, or a maintainer link) is a precedent. Precedents
are grouped by *kind of case*: the proposed relation plus a pattern read from the two tickets (e.g. "version
upgrade vs an earlier upgrade of the same library to a different version"). For a new proposal of a known kind:

  * if reviewers' past answers for that kind agree strongly enough that the one-sided lower bound on their
    agreement reaches the target, Assay applies their usual answer on its own (auto-accept / auto-reject);
  * otherwise the proposal goes to a person, with the precedents shown.

The AI model is never retrained; what is learned is which decisions no longer need a person.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from .bands import extra_needed
from .bounds import lower_bound

BUMP = re.compile(r"^\s*(upgrade|bump|update)\s+`?([\w .\-/]+?)`?\s+(?:to|from)\s+`?v?(\d[\w.\-]*)", re.I)
KINDS = {
    "bump-same-lib-diff-version": "a version upgrade vs an earlier upgrade of the same library to a different version",
    "bump-same-lib-same-version": "two upgrades of the same library to the same version",
    "same-title": "two tickets with the same title",
    "candidate-is-parent": "the earlier ticket is already the new ticket's parent",
    "siblings": "two sub-tasks of the same parent",
    "both-test-failures": "two failing or flaky test reports",
    "other": "no recognised pattern",
}
SOURCE_RANK = {"human": 3, "maintainer": 2, "ai": 1}


def agreeing_needed(agree: int, n: int, target: float, alpha: float = 0.05, cap: int = 100_000) -> int | None:
    """Smallest number of further decisions, all agreeing, that proves the pattern (lower bound >= target)."""
    for x in range(cap):
        if lower_bound(agree + x, n + x, alpha) >= target:
            return x
    return None


def _norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def case_kind(new: dict, cand: dict) -> str:
    """The pattern of a ticket pair, read only from the two tickets (never from the model or a label)."""
    mn, mc = BUMP.match(new.get("summary") or ""), BUMP.match(cand.get("summary") or "")
    if mn and mc and mn.group(2).lower().strip("` ") == mc.group(2).lower().strip("` "):
        return "bump-same-lib-" + ("same-version" if mn.group(3) == mc.group(3) else "diff-version")
    if _norm(new.get("summary")) and _norm(new.get("summary")) == _norm(cand.get("summary")):
        return "same-title"
    if new.get("parent") and new.get("parent") == cand.get("key"):
        return "candidate-is-parent"
    if new.get("parent") and new.get("parent") == cand.get("parent"):
        return "siblings"
    fail = re.compile(r"fail|flaky", re.I)
    if fail.search(new.get("summary") or "") and fail.search(cand.get("summary") or ""):
        return "both-test-failures"
    return "other"


def load_decisions(label_files: list[Path], human_files: list[Path] = (), clicks: list[dict] = ()) -> list[dict]:
    """One decision per (ticket, candidate, relation); a human answer beats a maintainer link beats an AI label."""
    out: dict[str, dict] = {}

    def add(r: dict, source: str):
        if r.get("correct") is None or r.get("relation") == "none" or not r.get("candidate"):
            return
        k = r.get("label_key") or f"{r['key']}|{r['candidate']}|{r['relation']}"
        d = {"id": k, "key": r["key"], "candidate": r["candidate"], "relation": r["relation"],
             "correct": bool(r["correct"]), "source": source}
        if k not in out or SOURCE_RANK[source] >= SOURCE_RANK[out[k]["source"]]:
            out[k] = d

    for p in label_files:
        for line in Path(p).read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                add(r, "maintainer" if r.get("reviewer") == "maintainer-link" else "ai")
    for p in human_files:
        for line in Path(p).read_text(encoding="utf-8").splitlines():
            if line.strip():
                add(json.loads(line), "human")
    for c in clicks:  # review-app decisions: accept = correct, reject = wrong
        if c.get("decision") in ("accept", "reject"):
            add({**c, "correct": c["decision"] == "accept"}, "human")
    return list(out.values())


def build_memory(decisions: list[dict], tickets: dict, *, target: float = 0.90, alpha: float = 0.05) -> dict:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for d in decisions:
        if d["key"] in tickets and d["candidate"] in tickets:
            groups[(d["relation"], case_kind(tickets[d["key"]], tickets[d["candidate"]]))].append(d)
    memory = {}
    for (relation, kind), ds in groups.items():
        n, yes = len(ds), sum(d["correct"] for d in ds)
        answer = "accept" if yes * 2 > n else "reject"
        agree = yes if answer == "accept" else n - yes
        low = lower_bound(agree, n, alpha)
        enabled = kind != "other" and low >= target  # "no recognised pattern" is never a precedent
        need = 0 if enabled else (extra_needed(agree, n, target, alpha) if kind != "other" else None)
        need_all = 0 if enabled else (agreeing_needed(agree, n, target, alpha) if kind != "other" else None)
        memory[f"{relation}/{kind}"] = {
            "relation": relation, "kind": kind, "kind_text": KINDS[kind], "n": n, "agree": agree, "answer": answer,
            "lower": round(low, 4), "target": target, "alpha": alpha, "enabled": enabled, "needs_more": need,
            "needs_agreeing": need_all,
            "sources": {s: sum(d["source"] == s for d in ds) for s in SOURCE_RANK},
            "examples": [f"{d['key']}->{d['candidate']}" for d in ds[:6]]}
    return memory


def resolve(new: dict, cand: dict, relation: str, memory: dict) -> dict:
    """What happens to one proposal: auto-accept / auto-reject from proven precedent, or ask a person."""
    kind = case_kind(new, cand)
    m = memory.get(f"{relation}/{kind}")
    if not m:
        return {"mode": "ask", "kind": kind, "reason": "No past decisions on this kind of case yet."}
    said = "accepted" if m["answer"] == "accept" else "rejected"
    if m["enabled"]:
        return {"mode": "auto-" + m["answer"], "kind": kind, "precedent": m,
                "reason": f"Reviewers {said} this kind of case ({m['kind_text']}) {m['agree']} of {m['n']} times; "
                          f"proven at {int(100 * m['target'])}%+, so it is handled without asking."}
    more = ""
    if m.get("needs_agreeing"):
        more = f" {m['needs_agreeing']} more agreeing reviews would prove it"
        more += (f" (about {m['needs_more']} at today's {100 * m['agree'] / m['n']:.0f}% agreement rate)."
                 if m.get("needs_more") and m["agree"] < m["n"] else ".")
    return {"mode": "ask", "kind": kind, "precedent": m,
            "reason": f"Reviewers {said} this kind of case {m['agree']} of {m['n']} times: not proven yet.{more}"}


def leave_one_out(decisions: list[dict], tickets: dict, *, target: float = 0.90, alpha: float = 0.05) -> dict:
    """Would reusing precedents have been right? Hide each decision, rebuild memory from the rest, predict it."""
    fired = right = 0
    misses = []
    for i, d in enumerate(decisions):
        if d["key"] not in tickets or d["candidate"] not in tickets:
            continue
        mem = build_memory(decisions[:i] + decisions[i + 1:], tickets, target=target, alpha=alpha)
        r = resolve(tickets[d["key"]], tickets[d["candidate"]], d["relation"], mem)
        if r["mode"].startswith("auto-"):
            fired += 1
            ok = (r["mode"] == "auto-accept") == d["correct"]
            right += ok
            if not ok:
                misses.append(d["id"])
    return {"target": target, "decisions": len(decisions), "auto_resolved": fired, "right": right,
            "precision": right / fired if fired else None,
            "lower_95": lower_bound(right, fired, 0.05) if fired else None, "misses": misses}
