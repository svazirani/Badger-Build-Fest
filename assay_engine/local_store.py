"""Local sandbox only: review and link are committed together, once per proposal."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from assay_triage.identity import digest, legacy_config


@contextmanager
def database(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA synchronous=FULL')
        db.execute('CREATE TABLE IF NOT EXISTS reviews (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS links (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        db.commit()
        yield db
    finally:
        db.close()


def proposal_id(row):
    return digest({k: row[k] for k in ("key", "candidate", "relation")} |
                  {"config_id": legacy_config(row)})


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
               "ts": datetime.now(timezone.utc).isoformat(), "scope": "local-sandbox"}
    with database(path) as db, db:
        db.execute('BEGIN IMMEDIATE')
        existing = db.execute('SELECT payload FROM reviews WHERE id=?', (receipt['id'],)).fetchone()
        if existing:
            return json.loads(existing[0]), False
        db.execute('INSERT INTO reviews VALUES (?,?)', (receipt['id'], json.dumps(receipt)))
        if decision == "accept":
            link = {**receipt, "status": "done", "path": "approved"}
            db.execute('INSERT INTO links VALUES (?,?)', (receipt['id'], json.dumps(link)))
    return receipt, True


def records(path, table="reviews"):
    if table not in ("reviews", "links"):
        raise ValueError("Unknown table")
    with database(path) as db:
        return [json.loads(r[0]) for r in db.execute(f'SELECT payload FROM {table} ORDER BY rowid DESC')]


def permission_status(config_id):
    # Stage 2 installs validated receipts; imported diagnostics never grant permission.
    return {"mode": "suggest", "config_id": config_id, "auto": False,
            "reason": "No validated permission receipt. Human approval required."}
