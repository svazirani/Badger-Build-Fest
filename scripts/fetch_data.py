"""Download the data files (git-ignored: too big for GitHub) from the Unity Catalog volume into data/.

    python scripts/fetch_data.py            # needs .env with DATABRICKS_HOST, DATABRICKS_TOKEN
    python scripts/fetch_data.py --upload   # the other direction: put local data/ files into the volume

The same files can be rebuilt from public Jira instead: python -m assay_triage.ingest && python -m assay_triage.retrieve --all
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from assay_triage import dbx  # noqa: E402

FILES = ["tickets.jsonl", "truth.jsonl", "candidates.jsonl", "candidates_all.jsonl", "judgments.jsonl"]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--upload", action="store_true")
    a = ap.parse_args()
    w = dbx.client()
    data = dbx.ROOT / "data"
    data.mkdir(exist_ok=True)
    for name in FILES:
        local, remote = data / name, f"{dbx.VOLUME}/{name}"
        if a.upload:
            if local.exists():
                print("uploaded", dbx.upload(local, w))
            continue
        local.write_bytes(w.files.download(remote).contents.read())
        print(f"{name:22s} {local.stat().st_size / 1e6:6.1f} MB")


if __name__ == "__main__":
    main()
