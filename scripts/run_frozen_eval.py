"""Run one configuration on a frozen plan. Dry-run unless explicit usage consent is supplied."""
import argparse
import json
import os
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from assay_triage.identity import resume_key
from assay_triage.judge import configuration, judge
from assay_triage.plans import validate


def load_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def write_jsonl_atomic(path, rows):
    """Replace the result file only after the complete new task is durable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix=path.name + ".", suffix=".tmp", delete=False) as stream:
        temp_path = Path(stream.name)
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp_path, path)


def total_task_cost(rows):
    """Task cost repeats on candidate rows; count each completed run once."""
    by_run = {}
    for row in rows:
        if row.get("task_status") == "complete" and row.get("task_cost_usd") is not None:
            by_run[row.get("run_id")] = float(row["task_cost_usd"])
    return sum(by_run.values())


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--plan", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--model", default="gpt-5-mini")
    ap.add_argument("--backend", choices=["cli", "anthropic", "openai", "databricks"], default="openai")
    ap.add_argument("--prompt", choices=["v1", "v2", "bad"], required=True)
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--i-accept-usage", action="store_true")
    a = ap.parse_args()
    plan = validate(json.loads(a.plan.read_text(encoding="utf-8")))
    config = configuration(a.model, a.backend, a.prompt, plan["k"], "stream-v1")
    existing = load_jsonl(a.out)
    expected = {resume_key(job["key"], config["config_id"], plan["plan_id"]): len(job["candidates"])
                for job in plan["jobs"]}
    counts = Counter(row.get("run_id") for row in existing
                     if row.get("task_status") == "complete"
                     and row.get("config_id") == config["config_id"]
                     and row.get("plan_id") == plan["plan_id"])
    complete = {run_id for run_id, count in counts.items() if count == expected.get(run_id)}
    pending = [job for job in plan["jobs"]
               if resume_key(job["key"], config["config_id"], plan["plan_id"]) not in complete]
    summary = {"plan_id": plan["plan_id"], "config_id": config["config_id"], "prompt": a.prompt,
               "backend": a.backend, "pending_calls": len(pending), "output": str(a.out)}
    if not a.execute:
        print(json.dumps({**summary, "mode": "dry-run", "model_calls": 0}, indent=2))
        return
    if not a.i_accept_usage or os.environ.get("ASSAY_ALLOW_MODEL_CALLS") != "1":
        ap.error("Execution requires --i-accept-usage and ASSAY_ALLOW_MODEL_CALLS=1")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    failures = a.out.with_suffix(a.out.suffix + ".failures.jsonl")
    for index, job in enumerate(pending, 1):
        run_id = resume_key(job["key"], config["config_id"], plan["plan_id"])
        candidates = [item["ticket"] for item in job["candidates"]]
        try:
            rows = judge(job["ticket"], candidates, a.model, a.backend, a.prompt, plan["k"], "stream-v1")
            for row in rows:
                row.update({"run_id": run_id, "plan_id": plan["plan_id"], "task_status": "complete",
                            "ts": time.time()})
            existing.extend(rows)
            write_jsonl_atomic(a.out, existing)
        except Exception as exc:
            with failures.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"run_id": run_id, "plan_id": plan["plan_id"], "key": job["key"],
                                         "config_id": config["config_id"], "error": str(exc)[:300],
                                         "task_status": "failed", "ts": time.time()}) + "\n")
        print(f"{index}/{len(pending)}", flush=True)
    print(json.dumps({**summary, "mode": "executed", "actual_cost_usd": total_task_cost(existing)}, indent=2))


if __name__ == "__main__":
    main()
