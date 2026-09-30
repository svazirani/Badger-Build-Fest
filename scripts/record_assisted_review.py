"""Record an approved, AI-assisted review into the Delta table <catalog>.<schema>.actions.

    python scripts/record_assisted_review.py results/assisted-review/2026-09-27-related-version-upgrades.json            # dry run
    python scripts/record_assisted_review.py results/assisted-review/2026-09-27-related-version-upgrades.json --write    # write

Each decision is stored as reviewer "<approver> (AI-assisted review)" with its reason, so the audit trail shows that an
assistant proposed the verdict and a person approved it. Re-running is safe: one row per suggestion (same id as a
click in the dashboard), updated in place.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from assay_triage import dbx  # noqa: E402

MERGE = """MERGE INTO {table} t USING (SELECT * FROM VALUES {values}
  AS s(id, key, candidate, relation, decision, user, reason, link, payload)) s
ON t.id = s.id
WHEN MATCHED THEN UPDATE SET decision = s.decision, user = s.user, reason = s.reason, ts = current_timestamp(),
  link_created = s.link, payload = s.payload
WHEN NOT MATCHED THEN INSERT (id, key, candidate, relation, config_id, decision, correction, user, reason, ts, link_created, payload)
VALUES (s.id, s.key, s.candidate, s.relation, 'assisted-review', s.decision, NULL, s.user, s.reason, current_timestamp(),
  s.link, s.payload)"""


def click_id(key: str, cand: str, relation: str) -> str:  # same id as a dashboard click (app/manager/server.py)
    return "manager:" + hashlib.sha256(f"{key}|{cand}|{relation}".encode()).hexdigest()[:40]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("review", type=Path)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    rev = json.loads(a.review.read_text(encoding="utf-8"))
    user = f"{rev['approved_by']} (AI-assisted review)"
    recs = rev["records"]
    print(f"{len(recs)} decisions ({rev['accept']} accept, {rev['reject']} reject) as \"{user}\"; rule: {rev['rule']}")
    if not a.write:
        print("dry run: add --write to record them")
        return
    table = dbx.table("actions")
    for start in range(0, len(recs), 50):
        chunk, values, params = recs[start:start + 50], [], []
        for i, r in enumerate(chunk):
            payload = {**{k: r[k] for k in ("key", "candidate", "relation", "decision", "reason")}, "user": user,
                       "source": "assisted-review", "proposed_by": rev["proposed_by"], "approved_by": rev["approved_by"],
                       "approved_at": rev["approved_at"], "review_file": str(a.review)}
            cols = [("id", click_id(r["key"], r["candidate"], r["relation"]), None), ("key", r["key"], None),
                    ("candidate", r["candidate"], None), ("relation", r["relation"], None), ("decision", r["decision"], None),
                    ("user", user, None), ("reason", r["reason"], None),
                    ("link", str(r["decision"] == "accept").lower(), "BOOLEAN"), ("payload", json.dumps(payload), None)]
            params += [{"name": f"{c}{i}", "value": v, "type": ty} for c, v, ty in cols]
            values.append("(" + ", ".join(f":{c}{i}" for c, _, _ in cols) + ")")
        dbx.sql(MERGE.format(table=table, values=", ".join(values)), params=params)
    rows = dbx.sql(f"SELECT decision, count(*) FROM {table} WHERE user = :u GROUP BY decision",
                   params=[{"name": "u", "value": user}])
    print("recorded:", {d: int(n) for d, n in rows})


if __name__ == "__main__":
    main()
