"""Build an exact task-level KEEP/DISCARD/UNPROVEN receipt."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from assay_engine.learning import build_gate, save_gate


def load(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--before", type=Path, required=True)
    ap.add_argument("--after", type=Path, required=True)
    ap.add_argument("--labels", type=Path, required=True)
    ap.add_argument("--before-config", required=True)
    ap.add_argument("--after-config", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    gate = build_gate(load(a.before), load(a.after), load(a.labels), a.before_config,
                      a.after_config, label=a.label)
    path = save_gate(gate, a.out)
    (a.out / f"gate-{a.label}-latest.json").write_text(json.dumps(gate, indent=2), encoding="utf-8")
    print(json.dumps({"gate": str(path), "verdict": gate["verdict"], "fixed": gate["fixed"],
                      "broke": gate["broke"], "n_adjudicated": gate["n_adjudicated"],
                      "excluded_unknown": gate["excluded_unknown"]}, indent=2))


if __name__ == "__main__":
    main()
