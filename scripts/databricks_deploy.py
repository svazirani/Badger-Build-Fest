"""Deploy the review workbench (app/workbench.py) as a Databricks App.

    python scripts/databricks_deploy.py              # stage, upload, create the app if needed, grant, deploy
    python scripts/databricks_deploy.py --name assay

On the platform the app reads its input files from the Unity Catalog volume and writes every review and sandbox link
to the Delta table <catalog>.<schema>.actions (ASSAY_STORE=delta). Free Edition apps stop 24 h after a deploy:
re-run this script to bring it back.
"""
from __future__ import annotations

import argparse
import io
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from assay_triage import dbx  # noqa: E402

ROOT = dbx.ROOT
STAGE = ROOT / "app" / "_bundle"
CODE = ["app/workbench.py", ".streamlit/config.toml", "assay_triage/__init__.py", "assay_triage/identity.py",
        "assay_triage/dbx.py", "assay_triage/plans.py", "assay_triage/judge.py"] + \
       [f"assay_engine/{p.name}" for p in sorted((ROOT / "assay_engine").glob("*.py"))]

APP_YAML = f"""command: ['streamlit', 'run', 'app/workbench.py']
env:
  - name: 'ASSAY_STORE'
    value: 'delta'
  - name: 'ASSAY_DATA_VOLUME'
    value: '{dbx.VOLUME}'
  - name: 'ASSAY_CATALOG'
    value: '{dbx.CATALOG}'
  - name: 'ASSAY_SCHEMA'
    value: '{dbx.SCHEMA}'
  - name: 'DATABRICKS_WAREHOUSE_ID'
    valueFrom: 'sql-warehouse'
  - name: 'STREAMLIT_BROWSER_GATHER_USAGE_STATS'
    value: 'false'
"""
REQUIREMENTS = "numpy\nscipy\n"


def stage() -> Path:
    shutil.rmtree(STAGE, ignore_errors=True)
    for rel in CODE:
        dst = STAGE / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, dst)
    runs = ROOT / "results" / "stage-2-3-runs"  # run rows, receipts and VERDICTS.md for the Trust / Model check pages
    for f in runs.rglob("*"):
        if f.is_file() and f.suffix in (".jsonl", ".json", ".md") and "first-pass" not in f.parts:
            dst = STAGE / f.relative_to(ROOT)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)
    (STAGE / "app.yaml").write_text(APP_YAML)
    (STAGE / "requirements.txt").write_text(REQUIREMENTS)
    return STAGE


def upload(w, src: Path, dest: str) -> None:
    from databricks.sdk.service.workspace import ImportFormat
    for p in sorted(src.rglob("*")):
        if p.is_file():
            target = f"{dest}/{p.relative_to(src).as_posix()}"
            w.workspace.mkdirs(target.rsplit("/", 1)[0])
            w.workspace.upload(target, io.BytesIO(p.read_bytes()), format=ImportFormat.AUTO, overwrite=True)


def main(argv=None):
    from databricks.sdk.service import apps
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="assay")
    a = ap.parse_args(argv)
    w = dbx.client()
    me = w.current_user.me().user_name
    dest = f"/Workspace/Users/{me}/{a.name}-app"
    src = stage()
    print(f"staged {sum(1 for p in src.rglob('*') if p.is_file())} files; uploading to {dest}", flush=True)
    upload(w, src, dest)

    names = {x.name for x in w.apps.list()}
    if a.name not in names:
        print(f"creating app {a.name} (a few minutes the first time)", flush=True)
        res = apps.AppResource(name="sql-warehouse", sql_warehouse=apps.AppResourceSqlWarehouse(
            id=os.environ["DATABRICKS_WAREHOUSE_ID"],
            permission=apps.AppResourceSqlWarehouseSqlWarehousePermission.CAN_USE))
        w.apps.create_and_wait(app=apps.App(name=a.name, resources=[res],
                                            description="Assay: proof engine for AI agents (review workbench)"))
    app = w.apps.get(a.name)
    sp = app.service_principal_client_id
    for g in (f"GRANT USE CATALOG ON CATALOG {dbx.CATALOG} TO `{sp}`",
              f"GRANT USE SCHEMA ON SCHEMA {dbx.CATALOG}.{dbx.SCHEMA} TO `{sp}`",
              f"GRANT SELECT, MODIFY ON TABLE {dbx.table('actions')} TO `{sp}`",
              f"GRANT READ VOLUME ON VOLUME {dbx.CATALOG}.{dbx.SCHEMA}.data TO `{sp}`"):
        dbx.sql(g, w)
    print(f"granted the app's service principal access to {dbx.CATALOG}.{dbx.SCHEMA}", flush=True)
    if app.compute_status and str(app.compute_status.state).endswith("STOPPED"):
        w.apps.start_and_wait(a.name)
    print("deploying...", flush=True)
    d = w.apps.deploy_and_wait(app_name=a.name, app_deployment=apps.AppDeployment(source_code_path=dest))
    print("deployment:", d.status.state if d.status else d)
    print("URL:", w.apps.get(a.name).url)


if __name__ == "__main__":
    main()
