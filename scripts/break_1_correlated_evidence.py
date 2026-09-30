"""Reproduce Break 1: correlated outputs must not amplify Assay's evidence.

This is a deterministic, zero-model-call stress test.  It contrasts the early
row-level calculation with the current permission-receipt path, then runs a
legitimate independent-task control and a shared-cause cluster attack.

    python scripts/break_1_correlated_evidence.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from assay_engine.bounds import lower_bound
from assay_engine.permissions import build_receipt, can_act
from assay_engine.policy import label_template


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "results" / "art-of-break" / "break-1-correlated-evidence.json"
CONFIG_ID = "break-1-demo"
COMPUTED_AT = "2026-09-27T08:00:00+00:00"
CHECKED_AT = "2026-09-27T08:30:00+00:00"


def row(key: str, candidate: str, relation: str = "duplicate") -> dict:
    return {
        "key": key,
        "candidate": candidate,
        "relation": relation,
        "confidence": 0.99,
        "config_id": CONFIG_ID,
        "plan_id": "break-1-frozen-plan",
        "run_id": f"{key}-{candidate}",
        "parsed": True,
        "task_status": "complete",
    }


def correct_labels(rows: list[dict]) -> list[dict]:
    labels = label_template(rows, CONFIG_ID)
    for label in labels:
        label.update(
            correct=True,
            reviewer="deterministic-break-fixture",
            reason="Fixture outcome is fixed before evaluation",
            label_status="adjudicated",
        )
    return labels


def decision(receipt: dict, relation: str) -> dict:
    return next(item for item in receipt["decisions"] if item["relation"] == relation)


def legacy_row_level_result(n: int, *, target: float, family_alpha: float) -> dict:
    """The unsafe calculation: every correct output row is independent evidence."""
    alpha = family_alpha / 3
    low = lower_bound(n, n, alpha)
    return {
        "evidence_n": n,
        "correct_k": n,
        "precision": 1.0,
        "lower_bound": round(low, 6),
        "decision": "auto" if low >= target else "suggest",
    }


def hardened_result(rows: list[dict], relation: str, *, target: float, family_alpha: float) -> dict:
    receipt = build_receipt(
        rows,
        correct_labels(rows),
        CONFIG_ID,
        target=target,
        family_alpha=family_alpha,
        computed_at=COMPUTED_AT,
    )
    result = decision(receipt, relation)
    mode, reason = can_act(receipt, relation, 0.99, CONFIG_ID, CHECKED_AT)
    return {
        "evidence_n": result["n"],
        "correct_k": result["k"],
        "precision": result["precision"],
        "lower_bound": round(result["lower"], 6),
        "decision": result["mode"],
        "can_act": mode,
        "can_act_reason": reason,
        "excluded": result["excluded"],
        "receipt_id": receipt["receipt_id"],
    }


def build_break_result(*, target: float = 0.90, family_alpha: float = 0.05) -> dict:
    attack_rows = [row("TASK-001", f"ACTION-{i:03d}") for i in range(50)]
    control_rows = [row(f"TASK-{i:03d}", f"ACTION-{i:03d}") for i in range(50)]
    cluster_rows = [row(f"TASK-{i:03d}", "SHARED-CAUSE-001", "part_of") for i in range(80)]

    attack = hardened_result(attack_rows, "duplicate", target=target, family_alpha=family_alpha)
    control = hardened_result(control_rows, "duplicate", target=target, family_alpha=family_alpha)
    cluster = hardened_result(cluster_rows, "part_of", target=target, family_alpha=family_alpha)

    return {
        "schema": 1,
        "break": "correlated-evidence-amplification",
        "claim": "One task or shared cause must not masquerade as many independent successes.",
        "method": "deterministic synthetic stress test; no model calls and no Jira data",
        "policy": {
            "target": target,
            "family_alpha": family_alpha,
            "relations": 3,
            "alpha_per_relation": family_alpha / 3,
        },
        "attack": {
            "description": "One underlying task emits 50 correct-looking outputs.",
            "raw_outputs": len(attack_rows),
            "unique_tasks": 1,
            "early_row_counter": legacy_row_level_result(
                len(attack_rows), target=target, family_alpha=family_alpha
            ),
            "hardened_receipt": attack,
            "passed": attack["decision"] != "auto" and attack["evidence_n"] == 1,
        },
        "independent_control": {
            "description": "Fifty independent tasks each emit one correct action.",
            "raw_outputs": len(control_rows),
            "unique_tasks": len(control_rows),
            "hardened_receipt": control,
            "passed": control["decision"] == "auto" and control["evidence_n"] == 50,
        },
        "shared_cause_attack": {
            "description": "Eighty tasks share one underlying cause/umbrella.",
            "raw_tasks": len(cluster_rows),
            "unique_clusters": 1,
            "hardened_receipt": cluster,
            "passed": (
                cluster["decision"] != "auto"
                and cluster["evidence_n"] == 1
                and cluster["excluded"]["dependent_sibling_action"] == 79
            ),
        },
    }


def summary(result: dict) -> str:
    attack = result["attack"]
    control = result["independent_control"]
    cluster = result["shared_cause_attack"]
    rows = [
        ("Correlated attack (early row counter)", attack["early_row_counter"]),
        ("Correlated attack (hardened)", attack["hardened_receipt"]),
        ("Independent control (hardened)", control["hardened_receipt"]),
        ("Shared-cause attack (hardened)", cluster["hardened_receipt"]),
    ]
    lines = [
        "Break 1: correlated-evidence amplification",
        "",
        f"{'Scenario':42} {'n':>4} {'lower':>9} {'decision':>10}",
        "-" * 69,
    ]
    for name, item in rows:
        lines.append(
            f"{name:42} {item['evidence_n']:>4} {item['lower_bound']:>9.3f} {item['decision']:>10}"
        )
    lines.extend(
        [
            "",
            "PASS" if all((attack["passed"], control["passed"], cluster["passed"])) else "FAIL",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    result = build_break_result()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(summary(result))
    print(f"\nEvidence: {args.out}")
    if not all(
        (
            result["attack"]["passed"],
            result["independent_control"]["passed"],
            result["shared_cause_attack"]["passed"],
        )
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
