"""Cheap, time-honest candidate search: TF-IDF over title + description + components.

A ticket may only be matched against tickets created BEFORE it (the agent can't see the future).
Research on duplicate detection finds simple lexical methods are strong baselines, so we start here.

    python -m assay_triage.retrieve --since 2025-01-01 --k 10     # candidates + recall report
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

DATA = Path(__file__).resolve().parent.parent / "data"


def load(name: str) -> list[dict]:
    p = DATA / name
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def doc(t: dict) -> str:
    return " ".join([t["summary"], t["summary"], " ".join(t.get("components") or []), (t.get("description") or "")[:1500]])


class Index:
    def __init__(self, tickets: list[dict]):
        self.tickets = tickets
        self.keys = [t["key"] for t in tickets]
        self.pos = {k: i for i, k in enumerate(self.keys)}
        self.created = np.array([t["created"] for t in tickets])
        self.parent = [t.get("parent") for t in tickets]
        small = len(tickets) < 10
        self.vec = TfidfVectorizer(sublinear_tf=True, min_df=1 if small else 2,
                                   max_df=1.0 if small else 0.5,
                                   ngram_range=(1, 2), stop_words="english")
        self.X = self.vec.fit_transform([doc(t) for t in tickets])

    def _top(self, sims: np.ndarray, k: int, mask: np.ndarray | None = None):
        if mask is not None:
            sims = np.where(mask, sims, -1.0)
        idx = np.argpartition(-sims, min(k, len(sims) - 1))[:k]
        idx = idx[np.argsort(-sims[idx])]
        return [{"key": self.keys[i], "score": round(float(sims[i]), 4)} for i in idx if sims[i] > 0]

    def candidates_for(self, key: str, k: int = 10, umbrellas: int = 3) -> list[dict]:
        i = self.pos[key]
        sims = (self.X @ self.X[i].T).toarray().ravel()
        mask = self.created < self.created[i]          # only earlier tickets
        top = self._top(sims, k, mask)
        # Sibling vote: a new sub-task resembles its siblings more than the umbrella itself, so the parents of
        # similar earlier tickets become umbrella candidates (scored by their best sibling's similarity).
        votes: dict[str, float] = {}
        for c in self._top(sims, 30, mask):
            p = self.parent[self.pos[c["key"]]]
            if p and p in self.pos and self.created[self.pos[p]] < self.created[i]:
                votes[p] = max(votes.get(p, 0.0), c["score"])
        have = {c["key"] for c in top}
        extra = [{"key": p, "score": round(v, 4), "via": "siblings"}
                 for p, v in sorted(votes.items(), key=lambda kv: -kv[1]) if p not in have][:umbrellas]
        return top + extra

    def search(self, text: str, k: int = 10) -> list[dict]:
        q = self.vec.transform([text])
        return self._top((self.X @ q.T).toarray().ravel(), k)


_INDEX: Index | None = None


def search(text: str, k: int = 10) -> list[dict]:
    """Live search used by the app's 'Try a ticket' page."""
    global _INDEX
    if _INDEX is None:
        _INDEX = Index(load("tickets.jsonl"))
    return _INDEX.search(text, k)


def all_candidates(tickets: list[dict], since: str = "2025-01-01", k: int = 5,
                   chunk_size: int = 128) -> list[dict]:
    """Retrieve for every eligible ticket without selecting on its outcome."""
    idx = Index(tickets)
    keys = sorted((t["key"] for t in tickets if t["created"] >= since),
                  key=lambda key: (idx.created[idx.pos[key]], key))
    rows = []
    for start in range(0, len(keys), chunk_size):
        batch = keys[start:start + chunk_size]
        positions = [idx.pos[key] for key in batch]
        similarities = (idx.X @ idx.X[positions].T).toarray()
        for column, (key, position) in enumerate(zip(batch, positions)):
            mask = idx.created < idx.created[position]
            rows.append({"key": key, "candidates": idx._top(similarities[:, column], k, mask)})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2025-01-01", help="evaluate tickets created on/after this date")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--all", action="store_true", help="retrieve every eligible ticket; do not select using truth")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    tickets = load("tickets.jsonl")
    truth = load("truth.jsonl")
    if a.all:
        rows = all_candidates(tickets, a.since, a.k)
        out = a.out or (DATA / "candidates_all.jsonl")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        scores = np.array([r["candidates"][0]["score"] for r in rows if r["candidates"]])
        quantiles = {f"q{int(q * 100)}": round(float(np.quantile(scores, q)), 4)
                     for q in (0, .25, .5, .75, .9, 1)} if scores.size else {}
        print(json.dumps({"tickets": len(rows), "with_candidates": int(scores.size),
                          "top_score_quantiles": quantiles, "out": str(out)}, indent=2))
        return
    idx = Index(tickets)
    by = {t["key"]: t for t in tickets}
    # evaluation set: every eval-period ticket that has a truth relation, plus an equal number without one
    rel_of = defaultdict(list)
    for r in truth:
        rel_of[r["src"]].append(r)
    eval_pos = [k for k in rel_of if by[k]["created"] >= a.since]
    rng = np.random.default_rng(0)
    neg_pool = [t["key"] for t in tickets if t["created"] >= a.since and t["key"] not in rel_of]
    eval_neg = list(rng.choice(neg_pool, size=min(len(neg_pool), len(eval_pos)), replace=False))
    rows, hit = [], Counter()
    tot = Counter()
    for key in eval_pos + eval_neg:
        c = idx.candidates_for(key, a.k)
        rows.append({"key": key, "candidates": c})
        got = {x["key"] for x in c}
        for r in rel_of.get(key, []):
            tot[r["relation"]] += 1
            hit[r["relation"]] += r["dst"] in got
    (DATA / "candidates.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(f"candidates for {len(rows)} eval tickets ({len(eval_pos)} with a truth relation, {len(eval_neg)} without)")
    for rel in sorted(tot):
        print(f"  recall@{a.k} {rel:10s} {hit[rel] / tot[rel]:.1%}  ({hit[rel]}/{tot[rel]})")


if __name__ == "__main__":
    main()
