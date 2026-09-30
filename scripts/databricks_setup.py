"""Put the Assay data into Unity Catalog: schema, volume, JSONL files, Delta tables.

    python scripts/databricks_setup.py            # everything (idempotent; re-run after new results)
    python scripts/databricks_setup.py --check    # only list what exists

Tables (catalog.schema from ASSAY_CATALOG / ASSAY_SCHEMA, default workspace.assay_triage):
tickets, truth, candidates, judgments (read from the volume) and actions (the app's review + link store).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from assay_triage import dbx  # noqa: E402

DATA = dbx.ROOT / "data"
FILES = ("tickets.jsonl", "truth.jsonl", "candidates.jsonl", "judgments.jsonl")

ACTIONS_DDL = f"""CREATE TABLE IF NOT EXISTS {dbx.table('actions')} (
  id STRING NOT NULL COMMENT 'proposal id: hash of key, candidate, relation, config',
  key STRING, candidate STRING, relation STRING, config_id STRING,
  decision STRING COMMENT 'accept | reject | correct', correction STRING,
  user STRING, reason STRING, ts TIMESTAMP,
  link_created BOOLEAN COMMENT 'true when the decision wrote a sandbox link (accept)',
  payload STRING COMMENT 'full receipt as JSON')
COMMENT 'Assay review decisions and the sandbox links they created. One row per proposal: the first decision wins.'"""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    w = dbx.client()
    if not a.check:
        dbx.sql(f"CREATE SCHEMA IF NOT EXISTS {dbx.CATALOG}.{dbx.SCHEMA} COMMENT 'Assay: proof engine demo on Apache Jira'", w)
        dbx.sql(f"CREATE VOLUME IF NOT EXISTS {dbx.CATALOG}.{dbx.SCHEMA}.data", w)
        for name in FILES:
            p = DATA / name
            if not p.exists():
                print(f"skip {name} (not in data/)")
                continue
            print(f"upload {name} ({p.stat().st_size / 1e6:.1f} MB) -> {dbx.upload(p, w)}", flush=True)
            dbx.sql(f"CREATE OR REPLACE TABLE {dbx.table(p.stem)} AS "
                    f"SELECT * FROM read_files('{dbx.VOLUME}/{name}', format => 'json')", w)
        dbx.sql(ACTIONS_DDL, w)
    for name in [Path(f).stem for f in FILES] + ["actions"]:
        try:
            n = dbx.sql(f"SELECT count(*) FROM {dbx.table(name)}", w)[0][0]
            print(f"  {dbx.table(name):40s} {n} rows")
        except Exception as e:  # noqa: BLE001
            print(f"  {dbx.table(name):40s} missing ({str(e)[:80]})")


if __name__ == "__main__":
    main()
