"""Build immutable Stage 2 permission receipts from adjudicated task actions."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from assay_engine.permissions import build_receipt, save_receipt


def load(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--judgments", type=Path, required=True)
    ap.add_argument("--labels", type=Path, required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--target", type=float, default=.90)
    ap.add_argument("--cutoff", type=float, default=.95)
    a = ap.parse_args()
    receipt = build_receipt(load(a.judgments), load(a.labels), a.config,
                            target=a.target, cutoff=a.cutoff)
    path = save_receipt(receipt, a.out)
    (a.out / "permission-latest.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps({"receipt": str(path), "receipt_id": receipt["receipt_id"],
                      "decisions": receipt["decisions"]}, indent=2))


if __name__ == "__main__":
    main()
