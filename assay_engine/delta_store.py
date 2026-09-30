"""Databricks store: the same interface as local_store, backed by the Delta table <catalog>.<schema>.actions.

One MERGE per decision writes the review and its sandbox link (link_created) in a single atomic statement, and
the MERGE only inserts when the proposal has no row yet, so retries and concurrent clicks create one link.
`path` arguments are accepted for interface compatibility and ignored.
"""
import json
import time
from datetime import datetime, timezone

from assay_engine.local_store import permission_status, proposal_id  # noqa: F401  (re-exported for the app)
from assay_triage import dbx
from assay_triage.identity import legacy_config

MERGE = f"""MERGE INTO {dbx.table('actions')} t USING (SELECT :id AS id) s ON t.id = s.id
WHEN NOT MATCHED THEN INSERT (id, key, candidate, relation, config_id, decision, correction, user, reason, ts,
                              link_created, payload)
VALUES (:id, :key, :candidate, :relation, :config_id, :decision, :correction, :user, :reason, current_timestamp(),
        :link_created, :payload)"""


def _p(name, value, type_=None):
    return {"name": name, "value": None if value is None else str(value), "type": type_}


def review(path, row, decision, user, reason="", correction=None):
    if decision not in ("accept", "reject", "correct"):
        raise ValueError("Unsupported decision")
    if row.get("relation") not in ("duplicate", "part_of", "related"):
        raise ValueError("Only link proposals can be reviewed")
    if not user.strip():
        raise ValueError("Reviewer is required")
    if decision == "correct" and correction not in ("duplicate", "part_of", "related", "none"):
        raise ValueError("A valid correction is required")
    receipt = {"id": proposal_id(row), "key": row["key"], "candidate": row["candidate"],
               "relation": row["relation"], "config_id": legacy_config(row), "decision": decision,
               "user": user.strip(), "reason": reason, "correction": correction,
               "ts": datetime.now(timezone.utc).isoformat(), "scope": "databricks-sandbox"}
    params = [_p(k, receipt[k]) for k in ("id", "key", "candidate", "relation", "config_id", "decision",
                                          "correction", "user", "reason")]
    params += [_p("link_created", "true" if decision == "accept" else "false", "BOOLEAN"),
               _p("payload", json.dumps(receipt))]
    for attempt in range(6):
        try:
            res = dbx.sql(MERGE, params=params)
            break
        except RuntimeError as e:  # concurrent MERGEs on one Delta table can conflict; the retry sees the winner
            if "concurrent" not in str(e).lower() or attempt == 5:
                raise
            time.sleep(0.5 * (attempt + 1))
    inserted = int(res[0][-1]) if res and res[0] else 0  # MERGE returns num_affected, updated, deleted, inserted
    if inserted:
        return receipt, True
    existing = dbx.sql(f"SELECT payload FROM {dbx.table('actions')} WHERE id = :id", params=[_p("id", receipt["id"])])
    return json.loads(existing[0][0]), False


def records(path=None, table="reviews"):
    if table not in ("reviews", "links"):
        raise ValueError("Unknown table")
    where = "WHERE link_created" if table == "links" else ""
    rows = dbx.sql(f"SELECT payload FROM {dbx.table('actions')} {where} ORDER BY ts DESC")
    out = [json.loads(r[0]) for r in rows]
    return [{**r, "status": "done", "path": "approved"} for r in out] if table == "links" else out
