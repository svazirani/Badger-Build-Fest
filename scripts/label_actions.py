"""Create or validate an independent, task-level adjudication worksheet."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from assay_engine.policy import label_template, prefill_from_truth, validate_labels


def load(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--judgments", type=Path, action="append")
    ap.add_argument("--config", action="append", default=[])
    ap.add_argument("--out", type=Path)
    ap.add_argument("--validate", type=Path)
    ap.add_argument("--min-confidence", type=float,
                    help="permission worksheets: keep only actions at/above the AUTO cutoff (the only ones a receipt uses)")
    ap.add_argument("--discordant-only", action="store_true",
                    help="gate worksheets (two --config): keep only tasks where the configs chose different actions; "
                         "the sign test's verdict depends only on those")
    ap.add_argument("--truth", type=Path, default=Path(__file__).resolve().parents[1] / "data" / "truth.jsonl",
                    help="maintainer links used to pre-fill labels they settle (use --truth none to skip)")
    a = ap.parse_args()
    if a.validate:
        labels = load(a.validate)
        validate_labels(labels)
        print(json.dumps({"labels": len(labels), "adjudicated": sum(r.get("correct") is not None for r in labels),
                          "unknown": sum(r.get("correct") is None for r in labels)}, indent=2))
        return
    if not a.judgments or not a.config or not a.out:
        ap.error("Template mode requires --judgments, one or more --config values, and --out")
    rows = [row for path in a.judgments for row in load(path)]
    labels = []
    seen = set()
    per_config = {c: {l["key"]: l for l in label_template(rows, c)} for c in a.config}
    keep = None
    if a.discordant_only:
        if len(a.config) != 2:
            ap.error("--discordant-only needs exactly two --config values")
        x, y = per_config.values()
        keep = {k for k in set(x) & set(y) if x[k]["label_key"] != y[k]["label_key"]}
    for config_id in a.config:
        for label in per_config[config_id].values():
            if keep is not None and label["key"] not in keep:
                continue
            if a.min_confidence is not None and (label["relation"] == "none" or label["confidence"] < a.min_confidence):
                continue
            if label["label_key"] not in seen:  # the same action under v1 and v2 is labelled once
                seen.add(label["label_key"])
                labels.append(label)
    if str(a.truth) != "none" and a.truth.exists():
        labels = prefill_from_truth(labels, rows, load(a.truth))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open("x", encoding="utf-8") as stream:
        for label in labels:
            stream.write(json.dumps(label, ensure_ascii=False) + "\n")
    print(json.dumps({"labels": len(labels), "prefilled_by_maintainer_links": sum(r.get("reviewer") == "maintainer-link" for r in labels),
                      "left_for_humans": sum(r.get("correct") is None for r in labels), "out": str(a.out), "model_calls": 0}, indent=2))


if __name__ == "__main__":
    main()
