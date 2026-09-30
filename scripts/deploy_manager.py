"""Deploy the manager dashboard (app/manager: FastAPI + one page) as the Databricks App "assay-manager".

    python scripts/sync_results.py         # first: put the results into Unity Catalog tables
    python scripts/deploy_manager.py       # stage, upload, create/update the app, grant, deploy

The app reads and writes only Unity Catalog tables through the SQL warehouse, and calls the Foundation Model
endpoints below for "Check new tickets now" (Free Edition: no per-call charge). Free Edition apps stop 24 h after
a deploy: re-run this script to bring it back.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from assay_triage import dbx  # noqa: E402
from scripts.databricks_deploy import upload  # noqa: E402

ROOT = dbx.ROOT
STAGE = ROOT / "app" / "manager" / "_bundle"
CODE = {"app/manager/server.py": "server.py", "app/manager/static/index.html": "static/index.html",
        "assay_triage/__init__.py": None, "assay_triage/dbx.py": None, "assay_triage/judge.py": None,
        "assay_triage/identity.py": None} | {f"assay_engine/{p.name}": None for p in (ROOT / "assay_engine").glob("*.py")} \
    | {f"app/manager/static/brand/{p.name}": f"static/brand/{p.name}" for p in (ROOT / "app/manager/static/brand").glob("*.png")}
ENDPOINTS = ["databricks-meta-llama-3-3-70b-instruct", "databricks-meta-llama-3-1-8b-instruct",  # every model the router
             "databricks-qwen3-next-80b-a3b-instruct", "databricks-gpt-oss-120b", "databricks-gpt-oss-20b",  # may pick
             "databricks-llama-4-maverick", "databricks-gemma-3-12b", "databricks-qwen35-122b-a10b"]
READ = ["proposals", "live_proposals", "past_decisions", "verdicts", "stream", "tickets", "routing_log", "actions",
        "heavy_scorecard", "heavy_summary", "heavy_cases"]
WRITE = ["actions", "live_proposals", "routing_log"]
APP_YAML = f"""command: ['uvicorn', 'server:app', '--host', '0.0.0.0', '--port', '8000']
env:
  - name: 'ASSAY_CATALOG'
    value: '{dbx.CATALOG}'
  - name: 'ASSAY_SCHEMA'
    value: '{dbx.SCHEMA}'
  - name: 'DATABRICKS_WAREHOUSE_ID'
    valueFrom: 'sql-warehouse'
  - name: 'ASSAY_ALLOW_MODEL_CALLS'
    value: '1'
"""
REQUIREMENTS = "fastapi\nuvicorn\nopenai\nnumpy\nscipy\n"


def stage() -> Path:
    shutil.rmtree(STAGE, ignore_errors=True)
    for src, dst in CODE.items():
        out = STAGE / (dst or src)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / src, out)
    (STAGE / "app.yaml").write_text(APP_YAML)
    (STAGE / "requirements.txt").write_text(REQUIREMENTS)
    return STAGE


def resources():
    from databricks.sdk.service import apps
    res = [apps.AppResource(name="sql-warehouse", sql_warehouse=apps.AppResourceSqlWarehouse(
        id=os.environ["DATABRICKS_WAREHOUSE_ID"], permission=apps.AppResourceSqlWarehouseSqlWarehousePermission.CAN_USE))]
    for ep in ENDPOINTS:
        res.append(apps.AppResource(name=ep.replace("databricks-", "").replace("meta-", "")[:30], serving_endpoint=apps.AppResourceServingEndpoint(
            name=ep, permission=apps.AppResourceServingEndpointServingEndpointPermission.CAN_QUERY)))
    return res


def main(argv=None):
    from databricks.sdk.service import apps
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="assay-manager")
    a = ap.parse_args(argv)
    w = dbx.client()
    dest = f"/Workspace/Users/{w.current_user.me().user_name}/{a.name}-app"
    src = stage()
    print(f"staged {sum(1 for p in src.rglob('*') if p.is_file())} files; uploading to {dest}", flush=True)
    upload(w, src, dest)
    desc = "Assay manager dashboard: what the triage agent did, what needs your OK, and what it has earned"
    if a.name not in {x.name for x in w.apps.list()}:
        print(f"creating app {a.name} (a few minutes the first time)", flush=True)
        w.apps.create_and_wait(app=apps.App(name=a.name, resources=resources(), description=desc))
    else:
        w.apps.update(a.name, app=apps.App(name=a.name, resources=resources(), description=desc))
    app = w.apps.get(a.name)
    sp = app.service_principal_client_id
    grants = [f"GRANT USE CATALOG ON CATALOG {dbx.CATALOG} TO `{sp}`",
              f"GRANT USE SCHEMA, CREATE TABLE ON SCHEMA {dbx.CATALOG}.{dbx.SCHEMA} TO `{sp}`"]
    grants += [f"GRANT SELECT{', MODIFY' if t in WRITE else ''} ON TABLE {dbx.table(t)} TO `{sp}`" for t in READ]
    for g in grants:
        dbx.sql(g, w)
    print(f"granted the app's service principal access to {len(READ)} tables", flush=True)
    if app.compute_status and str(app.compute_status.state).endswith("STOPPED"):
        w.apps.start_and_wait(a.name)
    print("deploying...", flush=True)
    d = w.apps.deploy_and_wait(app_name=a.name, app_deployment=apps.AppDeployment(source_code_path=dest))
    print("deployment:", d.status.state if d.status else d, "|", d.status.message if d.status else "")
    print("URL:", w.apps.get(a.name).url)


if __name__ == "__main__":
    main()
