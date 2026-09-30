"""Task-level action policy and independent human-label contract."""
from __future__ import annotations

from collections import defaultdict

from assay_triage.identity import digest

RELATIONS = ("duplicate", "part_of", "related")


def select_action(rows: list[dict]) -> dict:
    """Select exactly one deployed action for a task, or an explicit abstention."""
    if not rows:
        raise ValueError("A task needs at least one judgment row")
    task = rows[0].get("key")
    config_id = rows[0].get("config_id")
    if not task or not config_id:
        raise ValueError("Every row needs key and config_id")
    if any(r.get("key") != task or r.get("config_id") != config_id for r in rows):
        raise ValueError("Rows must describe one task and one configuration")
    choices = [r for r in rows if r.get("parsed") is not False and r.get("relation") in RELATIONS]
    if choices:
        chosen = sorted(choices, key=lambda r: (-float(r.get("confidence") or 0),
                                                str(r.get("candidate") or ""), r["relation"]))[0]
        action = {"key": task, "candidate": chosen["candidate"], "relation": chosen["relation"],
                  "confidence": float(chosen.get("confidence") or 0), "config_id": config_id,
                  "plan_id": chosen.get("plan_id"), "run_id": chosen.get("run_id")}
    else:
        first = rows[0]
        action = {"key": task, "candidate": None, "relation": "none", "confidence": 0.0,
                  "config_id": config_id, "plan_id": first.get("plan_id"), "run_id": first.get("run_id")}
    return {**action, "action_id": digest(action), "label_key": label_key(action)}


def label_key(action: dict) -> str:
    """What a human judges: this ticket, this candidate, this relation. Config and confidence don't change it."""
    return digest({"key": action["key"], "candidate": action.get("candidate"), "relation": action["relation"]})


def selected_actions(rows: list[dict], config_id: str) -> list[dict]:
    grouped = defaultdict(list)
    for row in rows:
        if row.get("config_id") == config_id and row.get("task_status", "complete") == "complete":
            grouped[row.get("key")].append(row)
    return [select_action(grouped[key]) for key in sorted(grouped)]


def label_template(rows: list[dict], config_id: str) -> list[dict]:
    return [{**action, "correct": None, "reviewer": "", "reason": "",
             "label_status": "unknown"} for action in selected_actions(rows, config_id)]


def validate_labels(labels: list[dict]) -> dict[str, dict]:
    out = {}
    for row in labels:
        action_id = row.get("label_key") or row.get("action_id")
        if not action_id or action_id in out:
            raise ValueError("Labels need unique label_key (or action_id) values")
        correct = row.get("correct")
        if correct not in (True, False, None):
            raise ValueError("correct must be true, false, or null")
        if correct is not None and not str(row.get("reviewer") or "").strip():
            raise ValueError("Adjudicated labels need a reviewer")
        out[action_id] = row
    return out


def scored_actions(rows: list[dict], labels: list[dict], config_id: str) -> list[dict]:
    by_id = validate_labels(labels)
    def label(action):
        return by_id.get(action["label_key"]) or by_id.get(action["action_id"]) or {}
    return [{**action, "correct": label(action).get("correct"),
             "label_status": label(action).get("label_status", "missing")}
            for action in selected_actions(rows, config_id)]


def prefill_from_truth(labels: list[dict], rows: list[dict], truth: list[dict]) -> list[dict]:
    """Settle what the maintainers' own links already decide; leave everything else for blind human review.

    - action X -> Y with relation R and a maintainer link X -> Y of type R: correct.
    - "no action", but a maintainer link joins the ticket to one of its shortlisted candidates: incorrect.
    Absence of a link proves nothing (maintainers miss real duplicates), so it is never used.
    """
    links = {(t["src"], t["dst"]): t["relation"] for t in truth}
    shortlist = defaultdict(set)
    for r in rows:
        shortlist[r.get("key")].add(r.get("candidate"))
    out = []
    for lab in labels:
        if lab.get("correct") is None:
            if lab["relation"] != "none" and links.get((lab["key"], lab.get("candidate"))) == lab["relation"]:
                lab = {**lab, "correct": True, "reviewer": "maintainer-link", "label_status": "adjudicated",
                       "reason": f"Apache maintainers linked {lab['key']} -> {lab['candidate']} as {lab['relation']}"}
            elif lab["relation"] == "none":
                hit = sorted(c for c in shortlist[lab["key"]] if (lab["key"], c) in links)
                if hit:
                    lab = {**lab, "correct": False, "reviewer": "maintainer-link", "label_status": "adjudicated",
                           "reason": f"Maintainers linked {lab['key']} -> {hit[0]} ({links[(lab['key'], hit[0])]})"}
        out.append(lab)
    return out
