"""Small Databricks helpers: workspace client from .env, SQL through the SQL warehouse, volume uploads.

Needs DATABRICKS_HOST, DATABRICKS_TOKEN (or Databricks Apps' built-in auth) and DATABRICKS_WAREHOUSE_ID.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG, SCHEMA = os.environ.get("ASSAY_CATALOG", "workspace"), os.environ.get("ASSAY_SCHEMA", "assay_triage")
VOLUME = f"/Volumes/{CATALOG}/{SCHEMA}/data"


def load_env(path: Path = ROOT / ".env") -> None:
    """Read KEY=value lines into os.environ (existing variables win). Never prints values."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def client():
    from databricks.sdk import WorkspaceClient
    load_env()
    return WorkspaceClient()


def table(name: str) -> str:
    return f"{CATALOG}.{SCHEMA}.{name}"


def sql(statement: str, w=None, params: list[dict] | None = None, timeout: int = 600) -> list[list]:
    """Run one statement on the SQL warehouse and return its rows (strings, as the API returns them)."""
    from databricks.sdk.service.sql import StatementParameterListItem, StatementState
    w = w or client()
    ps = [StatementParameterListItem(name=p["name"], value=p["value"], type=p.get("type")) for p in params or []]
    r = w.statement_execution.execute_statement(statement=statement, warehouse_id=os.environ["DATABRICKS_WAREHOUSE_ID"],
                                                parameters=ps or None, wait_timeout="50s")
    t0 = time.time()
    while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        if time.time() - t0 > timeout:
            w.statement_execution.cancel_execution(r.statement_id)
            raise TimeoutError(statement[:80])
        time.sleep(2)
        r = w.statement_execution.get_statement(r.statement_id)
    if r.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"{r.status.state}: {r.status.error.message if r.status.error else ''} | {statement[:120]}")
    rows = list(r.result.data_array or []) if r.result else []
    chunk = r.result.next_chunk_index if r.result else None
    while chunk is not None:
        c = w.statement_execution.get_statement_result_chunk_n(r.statement_id, chunk)
        rows += c.data_array or []
        chunk = c.next_chunk_index
    return rows


def upload(local: Path, w=None, dest_dir: str = VOLUME) -> str:
    w = w or client()
    dest = f"{dest_dir}/{local.name}"
    with open(local, "rb") as f:
        w.files.upload(dest, f, overwrite=True)
    return dest
