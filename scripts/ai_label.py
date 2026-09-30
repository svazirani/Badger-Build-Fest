"""AI adjudication of a blind label worksheet, kept separate from human labels.

    python scripts/ai_label.py results/stage-2-3-runs/gate-labels.jsonl --model databricks-gpt-oss-120b

Writes <worksheet>.ai.jsonl: the same rows with correct = true/false (or null when the labeller is unsure),
reviewer = "ai:<model>" and label_status = "ai-adjudicated" | "ai-unsure". Rows already settled by a maintainer
link are kept as they are. The labeller sees only ticket text: never the proposing model, prompt or confidence.
Human spot checks (scripts/spot_check.py) measure how far these labels can be trusted.
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from assay_triage.judge import call  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEFS = """Definitions (Apache Jira):
- duplicate: the same problem or request; one ticket should be closed in favour of the other.
- part_of: the NEW ticket is one piece of the bigger effort (umbrella/epic/parent) described by the EARLIER ticket.
  A sibling (another piece of the same umbrella) is NOT the umbrella.
- related: different problems that touch the same code or feature, where a maintainer would reasonably add a link.
  Sharing a component or a broad topic is not enough."""
SYSTEM = "You are a careful senior maintainer adjudicating ticket links. You answer with JSON only."


def fmt(t: dict, n: int = 1500) -> str:
    comp = ", ".join(t.get("components") or [])
    return f"{t.get('key')} ({t.get('issuetype')}) [{comp}]\nSummary: {t.get('summary')}\n{(t.get('description') or '')[:n]}"


def prompt_for(row: dict, by: dict, shortlist: list[str]) -> str:
    new = fmt(by.get(row["key"], {"key": row["key"]}))
    if row["relation"] == "none":
        cands = "\n\n".join(f"--- EARLIER {i + 1}\n{fmt(by.get(c, {'key': c}), 800)}" for i, c in enumerate(shortlist))
        q = ("Question: is the NEW ticket a duplicate of, part of, or related to ANY of the earlier tickets?\n"
             'Answer {"verdict": "yes" | "no" | "unsure", "confidence": 0.0-1.0, "reason": "<= 25 words"}.')
        return f"{DEFS}\n\n=== NEW\n{new}\n\n{cands}\n\n{q}"
    q = (f"Question: is the NEW ticket really \"{row['relation']}\" with respect to the EARLIER ticket?\n"
         'Answer {"verdict": "yes" | "no" | "unsure", "confidence": 0.0-1.0, "reason": "<= 25 words"}.')
    return f"{DEFS}\n\n=== NEW\n{new}\n\n=== EARLIER\n{fmt(by.get(row['candidate'], {'key': row['candidate']}))}\n\n{q}"


def parse(text: str) -> dict:
    s = text[text.find("{"): text.rfind("}") + 1]
    d = json.loads(s)
    if d.get("verdict") not in ("yes", "no", "unsure"):
        raise ValueError(f"bad verdict {d.get('verdict')!r}")
    return d


def adjudicate(row: dict, by: dict, shortlist: list[str], model: str, backend: str) -> dict:
    text, _, usage = call(prompt_for(row, by, shortlist), model, backend)
    d = parse(text)
    # For a "none" action the question is inverted: "yes, something relates" means the abstention was wrong.
    yes_means_correct = row["relation"] != "none"
    correct = None if d["verdict"] == "unsure" else ((d["verdict"] == "yes") == yes_means_correct)
    return {**row, "correct": correct, "reviewer": f"ai:{model}", "reason": str(d.get("reason", ""))[:300],
            "label_status": "ai-unsure" if correct is None else "ai-adjudicated",
            "ai_verdict": d["verdict"], "ai_confidence": d.get("confidence"), "ai_usage": usage}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("worksheet", type=Path)
    ap.add_argument("--model", default="databricks-gpt-oss-120b")
    ap.add_argument("--backend", default="databricks")
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args()
    labels = [json.loads(line) for line in a.worksheet.read_text(encoding="utf-8").splitlines() if line.strip()]
    by = {t["key"]: t for t in map(json.loads, (ROOT / "data" / "tickets.jsonl").read_text(encoding="utf-8").splitlines())}
    shortlists: dict[str, list[str]] = {}
    for p in (ROOT / "results" / "stage-2-3-runs").glob("*.jsonl"):
        if not p.name.endswith(("labels.jsonl", "failures.jsonl", ".ai.jsonl")) and not p.name.startswith("spot-check"):
            for line in p.read_text(encoding="utf-8").splitlines():
                r = json.loads(line)
                lst = shortlists.setdefault(r["key"], [])
                if r["candidate"] not in lst:
                    lst.append(r["candidate"])
    todo = [i for i, r in enumerate(labels) if r.get("correct") is None]

    def work(i):
        try:
            return i, adjudicate(labels[i], by, shortlists.get(labels[i]["key"], []), a.model, a.backend)
        except Exception as e:  # noqa: BLE001  (a failed call stays unknown, never guessed)
            return i, {**labels[i], "reviewer": f"ai:{a.model}", "label_status": "ai-failed", "reason": str(e)[:200]}

    with ThreadPoolExecutor(a.workers) as ex:
        for i, row in ex.map(work, todo):
            labels[i] = row
    out = a.worksheet.with_suffix(".ai.jsonl")
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in labels), encoding="utf-8")
    st = {s: sum(r.get("label_status") == s for r in labels) for s in ("adjudicated", "ai-adjudicated", "ai-unsure", "ai-failed")}
    print(json.dumps({"worksheet": a.worksheet.name, "out": str(out), "labels": len(labels), **st,
                      "correct": sum(r.get("correct") is True for r in labels),
                      "wrong": sum(r.get("correct") is False for r in labels)}))


if __name__ == "__main__":
    main()
