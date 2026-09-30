"""Human spot checks of AI labels: how far can the AI labeller be trusted?

    python scripts/spot_check.py make --n 20          # random sample of AI-labelled rows -> spot-check worksheet (AI answers hidden)
    streamlit run app/label_app.py -- results/stage-2-3-runs/spot-check.jsonl
    python scripts/spot_check.py compare              # agreement between humans and the AI labeller, with an interval
    python scripts/spot_check.py apply FILE.json      # apply adjudications {label_key: {correct, reason, reviewer}} to the .ai files
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from assay_engine.bounds import lower_bound, upper_bound  # noqa: E402

RUNS = Path(__file__).resolve().parents[1] / "results" / "stage-2-3-runs"
SPOT = RUNS / "spot-check.jsonl"
HIDE = ("correct", "reviewer", "reason", "label_status", "ai_verdict", "ai_confidence", "ai_usage", "confidence")


def load(p: Path) -> list[dict]:
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def ai_rows() -> dict[str, dict]:
    out = {}
    for p in sorted(RUNS.glob("*-labels.ai.jsonl")):
        for r in load(p):
            out[r["label_key"]] = {**r, "worksheet": p.name}
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    mk = sub.add_parser("make")
    mk.add_argument("--n", type=int, default=20)
    mk.add_argument("--seed", type=int, default=7)
    cmp_ = sub.add_parser("compare")
    cmp_.add_argument("--file", type=Path, default=SPOT)
    apl = sub.add_parser("apply")
    apl.add_argument("file", type=Path)
    a = ap.parse_args()

    if a.cmd == "make":
        pool = sorted(k for k, r in ai_rows().items() if r.get("label_status") == "ai-adjudicated")
        pick = random.Random(a.seed).sample(pool, min(a.n, len(pool)))
        rows = ai_rows()
        with SPOT.open("x", encoding="utf-8") as f:  # never overwrite human work
            for k in pick:
                r = {x: v for x, v in rows[k].items() if x not in HIDE}
                f.write(json.dumps({**r, "correct": None, "reviewer": "", "reason": "", "label_status": "unknown"}) + "\n")
        print(json.dumps({"spot_check": str(SPOT), "items": len(pick), "pool": len(pool), "seed": a.seed}))
    elif a.cmd == "compare":
        rows, human = ai_rows(), [r for r in load(a.file) if r.get("correct") is not None]
        pairs = [(h["correct"], rows[h["label_key"]]["correct"]) for h in human
                 if rows.get(h["label_key"], {}).get("correct") is not None]
        n, k = len(pairs), sum(x == y for x, y in pairs)
        print(json.dumps({"human_labelled": len(human), "compared": n, "agree": k,
                          "agreement": k / n if n else None,
                          "interval_90": [lower_bound(k, n, .05), upper_bound(k, n, .05)] if n else None,
                          "disagreements": [h["label_key"][:12] for h in human
                                            if rows.get(h["label_key"], {}).get("correct") not in (None, h["correct"])]},
                         indent=2))
    else:
        fixes = json.loads(a.file.read_text(encoding="utf-8"))
        done = 0
        for p in sorted(RUNS.glob("*-labels.ai.jsonl")):
            rows = load(p)
            for i, r in enumerate(rows):
                if r["label_key"] in fixes:
                    f = fixes[r["label_key"]]
                    rows[i] = {**r, "correct": f["correct"], "reason": f.get("reason", ""),
                               "reviewer": f.get("reviewer", "ai:claude-opus-5-5"),
                               "label_status": "ai-adjudicated" if f["correct"] is not None else "ai-unsure"}
                    done += 1
            p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        print(json.dumps({"applied": done, "requested": len(fixes)}))


if __name__ == "__main__":
    main()
