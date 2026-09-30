"""Reproduce Break 3: a small identical sample produced an invalid certificate.

The historical calculation is reproduced exactly for the degenerate input,
then compared with the hardened matched-pair quality interval.

    python scripts/break_3_invalid_certificate.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from assay_engine.compare import compare_models


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "results" / "art-of-break" / "break-3-invalid-certificate.json"


def pairs(n: int) -> list[dict]:
    return [{"item": i, "correct_a": True, "correct_b": True, "cost_a": 1.0, "cost_b": .4}
            for i in range(n)]


def historical_result(n: int = 30, margin: float = .02) -> dict:
    """Exact result of the old percentile bootstrap on identical differences."""
    quality_lo = quality_hi = 0.0
    cost_lo = cost_hi = .4 / 1.0 - 1.0
    verdict = "CERTIFY" if quality_lo > -margin and cost_hi < 0 else "INSUFFICIENT"
    return {"n": n, "quality_pp": 0.0, "quality_lo_pp": 0.0, "quality_hi_pp": 0.0,
            "cost_rel": -.6, "cost_lo": cost_lo, "cost_hi": cost_hi, "verdict": verdict,
            "failure": "zero-width quality interval from a degenerate percentile bootstrap"}


def build_break_result() -> dict:
    before = historical_result()
    after = compare_models(pairs(30))
    sizes = [30, 60, 100, 150, 400]
    sweep = []
    for n in sizes:
        result = compare_models(pairs(n))
        sweep.append({"n": n, "verdict": result["verdict"],
                      "quality_lo_pp": result["quality_lo_pp"]})
    return {
        "schema": 1,
        "break": "invalid-small-sample-cost-certificate",
        "claim": "No observed disagreement is not proof of equal quality.",
        "method": "deterministic synthetic matched pairs; no model calls",
        "red_test": {"expected": "INSUFFICIENT", "actual": before["verdict"], "exit_code": 1,
                     "assertion": "unsafe certificate: CERTIFY"},
        "before_hardening": before,
        "after_hardening": after,
        "sample_size_sweep": sweep,
        "passed": before["verdict"] == "CERTIFY" and after["verdict"] == "INSUFFICIENT",
        "lesson": "A bootstrap can collapse on identical observations; certification needs a non-degenerate exact safeguard.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    result = build_break_result()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    before, after = result["before_hardening"], result["after_hardening"]
    print("Break 3: invalid small-sample certificate")
    print(f"Before: n={before['n']}, quality interval=[0.0, 0.0] pp, decision={before['verdict']}")
    print(f"After:  n={after['n']}, quality interval=[{after['quality_lo_pp']:.1f}, "
          f"{after['quality_hi_pp']:.1f}] pp, decision={after['verdict']}")
    print("PASS" if result["passed"] else "FAIL")
    print(f"Evidence: {args.out}")
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
