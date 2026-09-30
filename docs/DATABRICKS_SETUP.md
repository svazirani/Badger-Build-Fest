# Running Assay Triage on Databricks (Free Edition)

This is a step-by-step guide for a teammate with a Databricks **Free Edition** account. It covers putting the Jira data in
Unity Catalog, calling Foundation Model APIs for the judge and embeddings, and deploying the Streamlit app as a
Databricks App.

## Quick start for a teammate taking over (current, Sat Sep 26 21:45 CDT)

Everything below the line is the original setup guide (written at 15:00, before the workspace existed). The
workspace, tables, data and the `assay-manager` app **already exist** (the workbench app `assay` was not redeployed after the Sep 27 move); to work on them you only need access and a `.env`.

1. **Get access.** Mohith (`nikesh@wisc.edu`, workspace owner since Sep 27) invites your email to the workspace (Settings → Identity and access → Users → Add user)
   and runs the grants (USE CATALOG `workspace`; all privileges on schema `workspace.assay_triage`; CAN_USE on the
   SQL warehouse; CAN_MANAGE on the apps `assay-manager` and `assay`). Anyone who will deploy or run
   `sync_results.py` also needs `MANAGE` on the schema, granted by name: the deploy script runs `GRANT`s and the sync
   replaces tables Mohith owns. Before deploying, agree who deploys: the last deploy replaces the app for everyone.
2. **Make your own token** (never share one): profile → Settings → Developer → Access tokens → Generate new token.
3. **Set up the repo:**
   ```bash
   git clone https://github.com/Ananda-001/Badger-Build-Fest.git && cd Badger-Build-Fest
   python3 -m venv .venv && source .venv/bin/activate     # Git Bash on Windows: source .venv/Scripts/activate
   pip install -r requirements.txt
   cat > .env <<'ENV'
   DATABRICKS_HOST=https://dbc-d5f34a78-6d29.cloud.databricks.com
   DATABRICKS_WAREHOUSE_ID=7caadfc08a5174fd
   DATABRICKS_TOKEN=<your own token>
   ENV
   python scripts/fetch_data.py        # data/*.jsonl from the volume (git-ignored, 60 MB)
   python -m pytest -q                 # 63 passed
   ```
4. **What lives where** (Unity Catalog `workspace.assay_triage`):

   | What | Where |
   |---|---|
   | Inputs | tables `tickets`, `truth`, `candidates`, `judgments`, `stream`; files in `/Volumes/workspace/assay_triage/data` |
   | Results (from `scripts/sync_results.py`) | `proposals`, `past_decisions`, `verdicts`; `precedents` (from `scripts/precedents.py --delta`) |
   | Live, written by the apps | `actions` (every Yes / No), `routing_log` (model switching), `live_proposals` |
   | Manager dashboard (the demo) | app `assay-manager`, code `app/manager/`, deploy `python scripts/deploy_manager.py` |
   | Review workbench (technical) | app `assay`, code `app/workbench.py`, deploy `python scripts/databricks_deploy.py` |
   | Models | Foundation Model APIs: Llama 3.3 70B (main), Llama 3.1 8B (not certified), Qwen3-Next 80B and gpt-oss 120B (backups). No Claude on Free Edition. |

5. **Common jobs:**
   ```bash
   python scripts/deploy_manager.py                        # redeploy the dashboard (apps stop 24 h after a deploy)
   python scripts/sync_results.py                          # after new results in results/: refresh the tables
   uvicorn app.manager.server:app --port 8000              # dashboard locally, same live tables
   ASSAY_ALLOW_MODEL_CALLS=1 python scripts/live_route.py --n 12 --delta   # live routing run ($0 on Free Edition)
   ```
   Model calls are free on Free Edition but rate-limited (HTTP 429 when many run at once). The full picture is in
   `docs/ASSAY_REPORT.md` (section 6 = Databricks, 8.8 = dashboard, 11 = commands).

---

Legend: **[verified]** = checked against docs.databricks.com on 2026-09-26. **[confirm with Xorbix]** = we could
not verify it for Free Edition specifically; ask the Xorbix mentors before relying on it.

---

## 0. What Free Edition gives you (and doesn't)

From the Free Edition limitations page [verified]:

| Area | Limit |
|---|---|
| Compute | Serverless only, "limited compute size and usage"; one SQL warehouse (2X-Small); no custom clusters |
| Model serving | Limited number of active endpoints; **no GPU, no provisioned throughput**; "certain models unavailable" |
| Databricks Apps | **Up to 3 apps per account**; an app **stops automatically 24 hours** after it is started, updated or redeployed |
| Vector search | One endpoint, one search unit |
| Jobs | Max 5 concurrent job tasks |
| Other | One workspace + one metastore; outbound internet limited to trusted domains; non-commercial use only |

Consequences for us:
- The judge must use the **pay-per-token Foundation Model APIs** (pre-provisioned endpoints). We can't create our own
  serving endpoints. Which pay-per-token models Free Edition actually exposes is **[confirm with Xorbix]**. Check the
  Serving page (step 3) to see what you have.
- Redeploy (or restart) the app on demo day so the 24-hour clock doesn't run out mid-judging.
- Fetching Jira from inside Databricks may be blocked by the outbound-internet allowlist **[confirm with Xorbix]**, so
  we ingest on a laptop and upload the `.jsonl` files.

## 1. Create the workspace

1. Go to <https://login.databricks.com/?dbx_source=docs&intent=CE_SIGN_UP> [verified].
2. Sign up with email (one-time code), Google, or Microsoft. Databricks creates the workspace for you. There's no cloud
   account to connect.
3. Note the workspace URL in the browser address bar, e.g. `https://dbc-xxxxxxxx-xxxx.cloud.databricks.com`. Below we
   call it `$HOST`.
4. The default catalog in a Free Edition workspace is `workspace` **[confirm with Xorbix]**. If yours differs,
   substitute it everywhere below.

## 2. Put the data in Unity Catalog

We keep the raw `.jsonl` files in a **volume** (the app and notebooks read them as files), and also expose them as
**tables** (for SQL, dashboards and Genie).

### 2a. Create a schema and a volume

In a SQL editor or notebook cell (`%sql`):

```sql
CREATE SCHEMA IF NOT EXISTS workspace.assay_triage;
CREATE VOLUME IF NOT EXISTS workspace.assay_triage.data;
```

Or in the UI [verified]: **Catalog** (left sidebar) → select `workspace` → select `assay_triage` → **Create** →
**Volume** → name `data`, type *Managed* → **Create**.

### 2b. Upload the files

Upload `data/tickets.jsonl`, `truth.jsonl`, `candidates.jsonl`, `judgments.jsonl`, and `feedback.jsonl` if it exists,
plus `model_compare.json`. **Never upload `data/sample/`**, which is fake.

UI [verified]: **+ New** → **Add or upload data** → **Upload files to a volume** → drag the files in → choose
`workspace.assay_triage.data` → upload. (Alternatively: **Catalog** → the volume → **Upload to this volume**.) The UI
upload limit is 5 GB per file [verified], so the 42 MB `tickets.jsonl` is fine.

CLI alternative (from the repo root, after `databricks auth login --host $HOST`):

```bash
for f in tickets truth candidates judgments; do
  databricks fs cp data/$f.jsonl dbfs:/Volumes/workspace/assay_triage/data/$f.jsonl --overwrite
done
```

### 2c. Make tables from the files

```sql
CREATE OR REPLACE TABLE workspace.assay_triage.tickets AS
  SELECT * FROM read_files('/Volumes/workspace/assay_triage/data/tickets.jsonl', format => 'json');
CREATE OR REPLACE TABLE workspace.assay_triage.truth AS
  SELECT * FROM read_files('/Volumes/workspace/assay_triage/data/truth.jsonl', format => 'json');
CREATE OR REPLACE TABLE workspace.assay_triage.judgments AS
  SELECT * FROM read_files('/Volumes/workspace/assay_triage/data/judgments.jsonl', format => 'json');
-- feedback grows while people use the app; re-run this to refresh it
CREATE OR REPLACE TABLE workspace.assay_triage.feedback AS
  SELECT * FROM read_files('/Volumes/workspace/assay_triage/data/feedback.jsonl', format => 'json');
```

(UI alternative [verified]: after uploading, select a file in the volume → **Create table** → pick catalog, schema and
table name.)

Sanity check: `SELECT relation, count(*) FROM workspace.assay_triage.truth GROUP BY 1;`

## 3. Pick the models

Pay-per-token endpoints appear under **Serving** (left sidebar), at the top of the Endpoints list [verified]. Open
**Playground** to try one interactively. The exact endpoint names below come from the supported-models page
[verified that they exist in Databricks; availability on Free Edition: **confirm with Xorbix**]:

| Role | First choice | Alternatives |
|---|---|---|
| Judge, small / cheap | `databricks-claude-haiku-4-5` | `databricks-gpt-5-4-mini`, `databricks-gpt-oss-20b`, `databricks-meta-llama-3-1-8b-instruct` |
| Judge, large / reference | `databricks-claude-sonnet-4-6` | `databricks-claude-sonnet-5`, `databricks-gpt-oss-120b`, `databricks-meta-llama-3-3-70b-instruct` |
| Embeddings (retrieval) | `databricks-gte-large-en` (1024-d, 8192-token window) | `databricks-bge-large-en` (1024-d, 512-token window), `databricks-qwen3-embedding-0-6b` (preview) |

The small-vs-large pair feeds the **Model check** page: run both on the same tickets, then `compare_models` tells us
whether the small one can replace the large one ("CERTIFIED, −70% cost, quality −0.4 pts [−1.9, +1.1]").

Note: newer docs also show models addressed as `system.ai.<model>` through an AI Gateway URL
(`$HOST/ai-gateway/mlflow/v1`) [verified that the docs show it]. Whether that route is enabled on Free Edition is
**[confirm with Xorbix]**. The classic `databricks-...` endpoint names below are what our code uses.

## 4. Call the models from a notebook

Create a notebook: **+ New** → **Notebook** (serverless compute attaches automatically). First cell:

```python
%pip install -U openai databricks-sdk
dbutils.library.restartPython()
```

**Chat (the judge)**. Use an OpenAI-compatible client pointed at the workspace's serving endpoints, with the
notebook's own token:

```python
from databricks.sdk import WorkspaceClient
from openai import OpenAI

w = WorkspaceClient()                                # picks up the notebook's identity automatically
token = w.config.authenticate()["Authorization"].split(" ", 1)[1]
client = OpenAI(base_url=f"{w.config.host}/serving-endpoints", api_key=token)

r = client.chat.completions.create(
    model="databricks-claude-haiku-4-5",
    messages=[{"role": "system", "content": "You triage software issue tickets. Answer with JSON only."},
              {"role": "user", "content": "NEW: NPE in join when right side is empty\nEARLIER: SPARK-123 NPE on empty join. Duplicate?"}],
    max_tokens=200)
print(r.choices[0].message.content)
```

The `$HOST/serving-endpoints` base URL is the long-standing pattern and is what `assay_triage/judge.py` uses. The
current docs page leads with `from databricks_openai import DatabricksOpenAI; client = DatabricksOpenAI()` (needs
`%pip install databricks-openai`) [verified], which does the same thing without handling the token yourself. If the
snippet above fails auth, try that one.

**Embeddings**:

```python
e = client.embeddings.create(model="databricks-gte-large-en", input=["NPE in join when right side is empty"])
print(len(e.data[0].embedding))   # 1024
```

**Running our judge on Databricks.** Clone the repo into the workspace (**Workspace** → **Create** → **Git folder**,
paste the GitHub URL), then in a notebook inside it:

```python
import os
os.environ["DATABRICKS_HOST"] = w.config.host
os.environ["DATABRICKS_TOKEN"] = token
from assay_triage.judge import judge_pair
# judge_pair(ticket_dict, candidate_dict, model="databricks-claude-haiku-4-5", backend="databricks")
```

From a laptop instead, create a personal access token under **Settings** → **Developer** → **Access tokens** →
**Generate new token** **[confirm with Xorbix that PATs are allowed on Free Edition]** and export `DATABRICKS_HOST` and
`DATABRICKS_TOKEN`.

Rate limits: pay-per-token endpoints have per-minute token and query limits that depend on the workspace tier
[verified in general; the Free Edition numbers are **confirm with Xorbix**]. Keep judge runs sequential, or use 2–4
threads at most, and retry on HTTP 429.

## 5. Deploy the Streamlit app as a Databricks App

The Apps runtime is Python 3.11. It installs `requirements.txt` with pip, and our `app.yaml` runs
`streamlit run app.py` [verified]. It also sets `STREAMLIT_SERVER_PORT`/`ADDRESS`/`HEADLESS`, `DATABRICKS_HOST` and the
app service principal's `DATABRICKS_CLIENT_ID`/`SECRET` [verified]. **Any single file over 10 MB fails the deploy**
[verified], which is why we build a bundle.

### 5a. Build the bundle (on your laptop)

```bash
~/.venvs/assay/bin/python app/make_bundle.py            # code + data (big .jsonl files are gzipped / sharded < 10 MB)
# or
~/.venvs/assay/bin/python app/make_bundle.py --no-data  # code only; the app downloads data from the volume
```

This writes `app/_bundle/`, containing `app.py`, `app_data.py`, `sample_data.py`, `app.yaml`, `requirements.txt`,
`assay_engine/`, `assay_triage/` and optionally `data/`.

### 5b. Create the app

UI [verified]: open the **app switcher** (top-right grid icon) → **Databricks Apps** (in some workspaces also
**+ New** → **App**) → **+ Create app** → **Create a custom app** → name `assay-triage` (lowercase letters, digits and
hyphens only; it can't be renamed later) → **Create app**.

Then, in the app's configuration, under **App resources** → **+ Add resource** [verified]:
- **Serving endpoint** `databricks-claude-haiku-4-5`, permission **Can query**. This lets "Try a ticket" ask the judge.
- **Volume** `workspace.assay_triage.data`, permission **Can read and write**. The app downloads the data on start and
  writes `feedback.jsonl` back, so reviews survive the 24-hour restarts. (Whether the service principal also needs an
  explicit `USE CATALOG`/`USE SCHEMA` grant is **[confirm with Xorbix]**.)

`app/app.yaml` already sets `ASSAY_JUDGE_BACKEND=databricks`, `ASSAY_JUDGE_MODEL=databricks-claude-haiku-4-5` and
`ASSAY_DATA_VOLUME=/Volumes/workspace/assay_triage/data`. Edit them if your catalog or model differs. Inside the app,
the judge authenticates with the app's own service-principal token (via `databricks-sdk`), so no PAT is needed.

### 5c. Upload and deploy

CLI [verified commands]:

```bash
databricks auth login --host $HOST
databricks sync app/_bundle /Workspace/Users/<your-email>/assay-triage-app
databricks apps deploy assay-triage --source-code-path /Workspace/Users/<your-email>/assay-triage-app
```

UI alternative [verified]: **Workspace** → your user folder → **Create** → **Folder** `assay-triage-app` → **Import**
the bundle files → back in the app, **Deploy** → select that folder → **Select** → **Deploy**.

Open the app URL shown on the app page. The sidebar shows "Signed in as <your email>". The app reads the
`X-Forwarded-Email` header that Databricks Apps forwards [verified], and every Accept/Reject is stamped with that name.

Troubleshooting:
- Deploy fails with "file too large": re-run `make_bundle.py`. It shards anything over 9.5 MB.
- The review queue says "No judgments yet": the volume download failed. Check the volume resource permission, or
  bundle the data without `--no-data`.
- "Try a ticket" shows "The judge could not be reached": check the serving-endpoint resource and the model name.

## 6. How the agent maps to "reads, decides, acts, improves"

| Challenge verb | What Assay Triage does | Where |
|---|---|---|
| **Reads** | Pulls each new Apache Jira ticket (Spark, Flink, Kafka, Hive) and shortlists earlier tickets it could relate to (TF-IDF now; `databricks-gte-large-en` embeddings as the upgrade), only ever looking at tickets created *before* it | `assay_triage/ingest.py`, `assay_triage/retrieve.py`, UC volume + tables |
| **Decides** | An LLM on the Foundation Model API judges each (ticket, candidate) pair as duplicate / part of umbrella / related / none, with a confidence and a one-line reason | `assay_triage/judge.py` → `judgments` |
| **Acts** | Each relation has proven confidence bands. In the **auto** band (precision lower bound ≥ 95%) it links on its own. In the **suggest** band it puts a card in the Review queue. In the **silent** band it stays quiet | `assay_engine.precision_bands` / `auto_threshold`; app pages *Review queue* and *Trust* |
| **Improves when a human corrects it** | Every Accept / Reject / Change relation is appended to `feedback.jsonl`, and each review becomes new evidence for the bands. Enough accepted reviews unlock auto for that relation ("need ~N more reviews to unlock auto for duplicates"), while rejections shrink the auto band. Learned changes (prompt or model swaps) are kept only if `gate_change` proves they help, and a cheaper model replaces the reference only if `compare_models` certifies it | `feedback` table, *Trust* page, *Model check* page |

Time rule (from `docs/SCHEMA.md`): tune only on tickets created before 2025-01-01, and evaluate on 2025-01-01 onward.

## 7. Open questions for Xorbix

1. Which pay-per-token chat and embedding endpoints are enabled on Free Edition (especially the Claude ones)?
2. Free Edition rate limits for pay-per-token endpoints.
3. Are personal access tokens allowed on Free Edition?
4. Is the default catalog `workspace`?
5. Does a volume resource on an App grant `USE CATALOG`/`USE SCHEMA` automatically?
6. Is the AI Gateway `system.ai.*` route available on Free Edition?
7. Can serverless notebooks reach `issues.apache.org`, or must ingestion run off-platform?
