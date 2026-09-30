"""Keyboard labelling in the terminal: one keypress per item, saved after every key.

    python scripts/quick_label.py results/stage-2-3-runs/spot-check.jsonl [--name krish]

Keys:  y / d = YES (right)    n / a = NO (wrong)    s / w = can't tell    u = undo last    q = quit (progress is saved)
The model's confidence and the AI labeller's answer are never shown.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
W = min(os.get_terminal_size().columns if sys.stdout.isatty() else 110, 140)


DEFS = """\033[2mDEFINITIONS (what Apache maintainers do)
  duplicate = the SAME problem/request; one would be closed for the other. Bumping the same library to a DIFFERENT
              version is NOT a duplicate (maintainers link only same-target-version bumps: 22 of 6,743 bump pairs).
  part of   = NEW is one piece of the EARLIER ticket's bigger effort (umbrella/epic). Two sibling pieces: NOT part of.
  related   = different problems in the same code/feature that a maintainer would link. Same topic alone: NO.\033[0m"""


def getkey() -> str:
    if not sys.stdin.isatty():
        return (sys.stdin.readline().strip() or "q")[0].lower()
    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        return sys.stdin.read(1).lower()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def block(t: dict, title: str, n: int) -> str:
    d = " ".join((t.get("description") or "").split())[:n]
    comp = ", ".join(t.get("components") or [])
    head = f"\033[1m{title} {t.get('key')}\033[0m ({t.get('issuetype')}) [{comp}]\n  \033[36m{t.get('summary')}\033[0m"
    return head + ("\n" + textwrap.fill(d, W, initial_indent="  ", subsequent_indent="  ") if d else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("worksheet", type=Path)
    ap.add_argument("--name", default=os.environ.get("USER", "human"))
    a = ap.parse_args()
    rows = [json.loads(line) for line in a.worksheet.read_text(encoding="utf-8").splitlines() if line.strip()]
    by = {t["key"]: t for t in map(json.loads, (ROOT / "data" / "tickets.jsonl").read_text(encoding="utf-8").splitlines())}
    shortlist: dict[str, list[str]] = {}
    for p in (ROOT / "results" / "stage-2-3-runs").glob("*.jsonl"):
        if not p.name.endswith(("labels.jsonl", "failures.jsonl", ".ai.jsonl")) and not p.name.startswith("spot-check"):
            for line in p.read_text(encoding="utf-8").splitlines():
                r = json.loads(line)
                s = shortlist.setdefault(r["key"], [])
                if r["candidate"] not in s:
                    s.append(r["candidate"])
    history: list[int] = []

    def save():
        tmp = a.worksheet.with_suffix(".tmp")
        tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        os.replace(tmp, a.worksheet)

    while True:
        todo = [i for i, r in enumerate(rows) if r.get("correct") is None and r.get("label_status") != "skipped"]
        if not todo:
            print(f"\nAll {len(rows)} done. Saved to {a.worksheet}")
            return
        i = todo[0]
        r = rows[i]
        print("\033[2J\033[H", end="")
        print(f"[{len(rows) - len(todo) + 1}/{len(rows)}]  y/d = YES   n/a = NO   s/w = can't tell   u = undo   q = quit")
        print(DEFS + "\n")
        print(block(by.get(r["key"], {"key": r["key"]}), "NEW", 900) + "\n")
        if r["relation"] == "none":
            for c in shortlist.get(r["key"], []):
                print(block(by.get(c, {"key": c}), "EARLIER", 250) + "\n")
            print(f"\033[1;33mThe agent linked {r['key']} to NOTHING. Is that right (no duplicate/umbrella/related above)?\033[0m")
        else:
            print(block(by.get(r["candidate"], {"key": r["candidate"]}), "EARLIER", 900) + "\n")
            print(f"\033[1;33mIs {r['key']} really  {r['relation'].upper().replace('_', ' ')}  {r['candidate']} ?\033[0m")
        k = getkey()
        if k in ("q", "\x03"):
            print("\nSaved. Run again to continue.")
            return
        if k == "u" and history:
            j = history.pop()
            rows[j] = {**rows[j], "correct": None, "reviewer": "", "label_status": "unknown"}
        elif k in ("y", "d", "n", "a", "s", "w"):
            if k in ("s", "w"):
                rows[i] = {**r, "correct": None, "reviewer": a.name, "label_status": "skipped"}
            else:
                rows[i] = {**r, "correct": k in ("y", "d"), "reviewer": a.name, "label_status": "adjudicated"}
            history.append(i)
        save()


if __name__ == "__main__":
    main()
