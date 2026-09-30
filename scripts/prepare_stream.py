"""Create disjoint, outcome-blind Stage 2/3 plans. Makes zero model calls."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from assay_triage.plans import freeze_stream, save


def load(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, default=Path(__file__).resolve().parents[1] / "data")
    ap.add_argument("--out", type=Path, default=Path("results/stage-2-3-plans"))
    ap.add_argument("--min-score", type=float, required=True)
    ap.add_argument("--permission-n", type=int, default=90)
    ap.add_argument("--gate-n", type=int, default=60)
    ap.add_argument("--stress-n", type=int, default=30)
    a = ap.parse_args()
    tickets = load(a.data / "tickets.jsonl")
    candidates = load(a.data / "candidates_all.jsonl")
    permission = freeze_stream(tickets, candidates, n=a.permission_n, seed=11, min_score=a.min_score)
    gate = freeze_stream(tickets, candidates, n=a.gate_n, seed=23, min_score=a.min_score,
                         excluded={j["key"] for j in permission["jobs"]})
    stress = freeze_stream(tickets, candidates, n=a.stress_n, seed=37, min_score=a.min_score,
                           excluded={j["key"] for j in permission["jobs"] + gate["jobs"]},
                           slice_pattern=r"\b(upgrade|bump|update)\b.*\d")
    a.out.mkdir(parents=True, exist_ok=True)
    for name, plan in (("permission", permission), ("gate", gate), ("stress", stress)):
        save(plan, a.out / f"{name}.json")
    print(json.dumps({name: {"plan_id": plan["plan_id"], "tasks": len(plan["jobs"]),
                             "eligible": plan["eligible_n"], "model_calls": 0}
                      for name, plan in (("permission", permission), ("gate", gate), ("stress", stress))}, indent=2))


if __name__ == "__main__":
    main()
