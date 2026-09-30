"""Exact paired correction gate over independently adjudicated task actions."""
from __future__ import annotations

import json
from pathlib import Path
from scipy import stats

from assay_triage.identity import digest
from .policy import scored_actions


def build_gate(before_rows: list[dict], after_rows: list[dict], labels: list[dict],
               before_config: str, after_config: str, *, family_alpha: float = 0.05,
               comparisons: int = 2, label: str = "v1-to-v2") -> dict:
    if comparisons < 1:
        raise ValueError("comparisons must be positive")
    before_plans = {r.get("plan_id") for r in before_rows if r.get("plan_id")}
    after_plans = {r.get("plan_id") for r in after_rows if r.get("plan_id")}
    if len(before_plans) != 1 or before_plans != after_plans:
        raise ValueError("Before and after must be complete outputs from the same frozen plan")
    before = {a["key"]: a for a in scored_actions(before_rows, labels, before_config)}
    after = {a["key"]: a for a in scored_actions(after_rows, labels, after_config)}
    common = sorted(set(before) & set(after))
    # Same action before and after = the same outcome whatever the truth: a tie for the sign test, no label needed.
    same = [key for key in common if before[key].get("label_key") and before[key]["label_key"] == after[key]["label_key"]]
    labelled = [key for key in common if key not in same
                and before[key]["correct"] is not None and after[key]["correct"] is not None]
    usable = []
    seen_clusters = set()
    for key in labelled:
        part_of = [a["candidate"] for a in (before[key], after[key]) if a["relation"] == "part_of"]
        cluster = ("part_of", min(part_of)) if part_of else ("ticket", key)
        if cluster not in seen_clusters:
            usable.append(key)
            seen_clusters.add(cluster)
    fixed = [key for key in usable if not before[key]["correct"] and after[key]["correct"]]
    broke = [key for key in usable if before[key]["correct"] and not after[key]["correct"]]
    discordant = len(fixed) + len(broke)
    alpha = family_alpha / comparisons
    p_keep = stats.binomtest(len(fixed), discordant, 0.5, alternative="greater").pvalue if discordant else 1.0
    p_discard = stats.binomtest(len(broke), discordant, 0.5, alternative="greater").pvalue if discordant else 1.0
    verdict = "KEEP" if p_keep <= alpha else "DISCARD" if p_discard <= alpha else "UNPROVEN"
    content = {"schema": 1, "kind": "learning-gate", "label": label,
               "before_config_id": before_config, "after_config_id": after_config,
               "method": "exact paired sign test on discordant task outcomes",
               "family_alpha": family_alpha, "comparisons": comparisons, "alpha": alpha,
               "unit": "task, deduplicated by predicted part-of umbrella", "n_common": len(common),
               "n_same_action": len(same), "n_adjudicated": len(usable),
               "excluded_unknown": len(common) - len(same) - len(labelled),
               "excluded_dependent": len(labelled) - len(usable), "fixed": len(fixed), "broke": len(broke),
               "unchanged": len(usable) - len(fixed) - len(broke) + len(same),
               "observed_delta": ((len(fixed) - len(broke)) / len(usable)) if usable else None,
               "p_keep": p_keep, "p_discard": p_discard, "verdict": verdict,
               "fixed_tasks": fixed, "broke_tasks": broke,
               "sources": {"before_sha256": digest(before_rows), "after_sha256": digest(after_rows),
                           "labels_sha256": digest(labels)}}
    return {**content, "gate_id": digest(content)}


def save_gate(gate: dict, directory: Path) -> Path:
    content = {k: v for k, v in gate.items() if k != "gate_id"}
    if digest(content) != gate.get("gate_id"):
        raise ValueError("Gate hash mismatch")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"gate-{gate['gate_id']}.json"
    with path.open("x", encoding="utf-8") as stream:
        json.dump(gate, stream, ensure_ascii=False, indent=2)
    return path
