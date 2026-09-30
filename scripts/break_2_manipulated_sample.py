"""Reproduce Break 2: an easy evaluation sample can fake permission.

The population outcomes are fixed first.  The early/enriched path selects the
known successes; the hardened path freezes uniform samples without seeing those
outcomes.  No model, Jira, network, or Databricks call is made.

    python scripts/break_2_manipulated_sample.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from assay_engine.permissions import build_receipt
from assay_engine.policy import label_template
from assay_triage.plans import freeze_stream, validate


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "results" / "art-of-break" / "break-2-manipulated-sample.json"
CONFIG_ID = "break-2-demo"
COMPUTED_AT = "2026-09-27T08:00:00+00:00"


def population(n: int = 200, successful: int = 50) -> tuple[list[dict], list[dict], dict[str, bool]]:
    tickets = [{"key": "REFERENCE", "created": "2024-01-01", "summary": "Earlier reference"}]
    candidates = []
    outcomes = {}
    for i in range(n):
        key = f"TASK-{i:03d}"
        tickets.append({"key": key, "created": "2025-01-02", "summary": f"Task {i}"})
        candidates.append({"key": key, "candidates": [{"key": "REFERENCE", "score": .8}]})
        outcomes[key] = i < successful
    return tickets, candidates, outcomes


def permission_for(keys: list[str], outcomes: dict[str, bool]) -> dict:
    rows = [{
        "key": key,
        "candidate": "REFERENCE",
        "relation": "duplicate",
        "confidence": .99,
        "config_id": CONFIG_ID,
        "plan_id": "break-2-frozen-plan",
        "run_id": key,
        "parsed": True,
        "task_status": "complete",
    } for key in keys]
    labels = label_template(rows, CONFIG_ID)
    for label in labels:
        label.update(correct=outcomes[label["key"]], reviewer="fixed-fixture",
                     reason="Outcome fixed before sampling", label_status="adjudicated")
    receipt = build_receipt(rows, labels, CONFIG_ID, computed_at=COMPUTED_AT)
    return receipt["decisions"][0]


def build_break_result(seeds: int = 100) -> dict:
    tickets, candidates, outcomes = population()
    easy_keys = [key for key, correct in outcomes.items() if correct]
    enriched = permission_for(easy_keys, outcomes)

    honest = []
    for seed in range(seeds):
        plan = validate(freeze_stream(tickets, candidates, n=50, seed=seed, min_score=.7))
        decision = permission_for([job["key"] for job in plan["jobs"]], outcomes)
        honest.append({"seed": seed, "n": decision["n"], "k": decision["k"],
                       "precision": decision["precision"], "lower": decision["lower"],
                       "decision": decision["mode"], "plan_id": plan["plan_id"]})

    false_auto = sum(item["decision"] == "auto" for item in honest)
    first = honest[0]
    return {
        "schema": 1,
        "break": "outcome-selected-evaluation-sample",
        "claim": "An evaluation chosen with knowledge of outcomes can make unsafe autonomy look proven.",
        "method": "deterministic synthetic population; no model calls and no Jira data",
        "population": {"tasks": len(outcomes), "correct": sum(outcomes.values()),
                       "precision": sum(outcomes.values()) / len(outcomes)},
        "enriched_attack": {
            "selection": "all 50 known successes",
            "n": enriched["n"], "k": enriched["k"], "precision": enriched["precision"],
            "lower": enriched["lower"], "decision": enriched["mode"],
            "unsafe": enriched["mode"] == "auto",
        },
        "outcome_blind_example": first,
        "outcome_blind_trials": {
            "trials": seeds,
            "false_auto": false_auto,
            "auto_rate": false_auto / seeds,
            "min_correct": min(item["k"] for item in honest),
            "max_correct": max(item["k"] for item in honest),
        },
        "passed": enriched["mode"] == "auto" and false_auto == 0,
        "lesson": "Define and hash the deployment-like stream before outcomes; never certify on an enriched sample.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    result = build_break_result()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("Break 2: outcome-selected sample")
    print(f"Population: {result['population']['correct']}/{result['population']['tasks']} correct "
          f"({result['population']['precision']:.0%})")
    attack = result["enriched_attack"]
    trials = result["outcome_blind_trials"]
    print(f"Enriched sample: {attack['k']}/{attack['n']}, lower={attack['lower']:.3f}, "
          f"decision={attack['decision'].upper()}")
    print(f"Outcome-blind samples: false AUTO in {trials['false_auto']}/{trials['trials']} trials")
    print("PASS" if result["passed"] else "FAIL")
    print(f"Evidence: {args.out}")
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
