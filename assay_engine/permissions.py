"""Immutable, configuration-scoped permission receipts with family-wise control."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from assay_triage.identity import digest
from .bands import extra_needed
from .bounds import lower_bound
from .policy import RELATIONS, scored_actions


def build_receipt(rows: list[dict], labels: list[dict], config_id: str, *, target: float = 0.90,
                  cutoff: float = 0.95, family_alpha: float = 0.05, valid_hours: int = 24,
                  computed_at: str | None = None) -> dict:
    if not 0 < target < 1 or not 0 < cutoff <= 1 or not 0 < family_alpha < 1:
        raise ValueError("Invalid target, cutoff, or alpha")
    actions = scored_actions(rows, labels, config_id)
    alpha_each = family_alpha / len(RELATIONS)
    decisions = []
    for relation in RELATIONS:
        raw_eligible = [a for a in actions if a["relation"] == relation and a["confidence"] >= cutoff]
        if relation == "part_of":
            # One outcome-independent representative per predicted umbrella avoids
            # treating sibling tickets as independent proof.
            eligible = []
            seen_umbrellas = set()
            for action in sorted(raw_eligible, key=lambda a: (str(a["candidate"]), a["key"])):
                if action["candidate"] not in seen_umbrellas:
                    eligible.append(action)
                    seen_umbrellas.add(action["candidate"])
        else:
            eligible = raw_eligible
        labelled = [a for a in eligible if a["correct"] is not None]
        n, k = len(labelled), sum(a["correct"] is True for a in labelled)
        precision = k / n if n else None
        low = lower_bound(k, n, alpha_each) if n else 0.0
        mode = "auto" if n and low >= target else ("quiet" if n and precision < 0.5 else "suggest")
        # "needs N more" labelled actions in the zone if precision holds (None: the target is out of reach at this rate)
        need = extra_needed(k, n, target, alpha_each) if n and mode != "auto" else (0 if mode == "auto" else None)
        decisions.append({"relation": relation, "mode": mode, "threshold": cutoff, "n": n, "k": k,
                          "needs_more": need,
                          "precision": precision, "lower": low, "target": target, "alpha": alpha_each,
                          "evidence_action_ids": [a["action_id"] for a in labelled],
                          "excluded": {"unknown_or_missing_label": len(eligible) - n,
                                       "dependent_sibling_action": len(raw_eligible) - len(eligible),
                                       "below_threshold_or_other_action": len(actions) - len(raw_eligible)}})
    now = datetime.fromisoformat(computed_at) if computed_at else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    content = {"schema": 1, "kind": "permission-receipt", "config_id": config_id,
               "policy": {"unit": "one deterministic action per ticket; one representative per part-of umbrella",
                          "part_of_target": "precision across sampled predicted umbrellas", "cutoff": cutoff,
                          "target": target, "family_alpha": family_alpha,
                          "multiplicity": "Bonferroni across three relations",
                          "labels": "independent adjudication; unknown excluded"},
               "computed_at": now.isoformat(), "valid_until": (now + timedelta(hours=valid_hours)).isoformat(),
               "sources": {"judgments_sha256": digest(rows), "labels_sha256": digest(labels)},
               "decisions": decisions}
    return {**content, "receipt_id": digest(content)}


def validate_receipt(receipt: dict) -> dict:
    content = {k: v for k, v in receipt.items() if k != "receipt_id"}
    if digest(content) != receipt.get("receipt_id"):
        raise ValueError("Permission receipt hash mismatch")
    if receipt.get("kind") != "permission-receipt":
        raise ValueError("Wrong receipt kind")
    return receipt


def save_receipt(receipt: dict, directory: Path) -> Path:
    validate_receipt(receipt)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"permission-{receipt['receipt_id']}.json"
    with path.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2)
    return path


def can_act(receipt: dict | None, relation: str, confidence: float, config_id: str,
            now: str | None = None) -> tuple[str, str]:
    try:
        validate_receipt(receipt or {})
        if receipt["config_id"] != config_id:
            return "suggest", "Configuration does not match the evaluated receipt."
        current = datetime.fromisoformat(now) if now else datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        if current >= datetime.fromisoformat(receipt["valid_until"]):
            return "suggest", "Permission receipt has expired."
        decision = next(d for d in receipt["decisions"] if d["relation"] == relation)
        if decision["mode"] == "auto" and float(confidence) >= decision["threshold"]:
            return "auto", f"Authorized by receipt {receipt['receipt_id'][:12]}."
        if decision["mode"] == "auto":
            return "suggest", "Confidence is below the receipt's AUTO threshold."
        return decision["mode"], "Action is outside the receipt's AUTO scope."
    except (KeyError, StopIteration, TypeError, ValueError):
        return "suggest", "No valid permission receipt. Human approval required."
