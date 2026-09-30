"""Blind labelling page for Stage 2/3 worksheets (made by scripts/label_actions.py).

    streamlit run app/label_app.py -- results/stage-2-3-runs/gate-labels.jsonl

Shows the new ticket and the proposed candidate side by side, never the model's confidence or which prompt/model
proposed it. For a "no action" row it shows every shortlisted candidate: the action is right only if none of them
is a real duplicate / umbrella / related ticket. Every click rewrites the worksheet atomically.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]


@st.cache_data
def tickets():
    rows = (ROOT / "data" / "tickets.jsonl").read_text(encoding="utf-8").splitlines()
    return {t["key"]: t for t in map(json.loads, filter(None, rows))}


@st.cache_data
def shortlists():
    out = {}
    for p in (ROOT / "results" / "stage-2-3-runs").glob("*.jsonl"):
        if p.name.endswith(("labels.jsonl", "failures.jsonl", ".ai.jsonl")) or p.name.startswith("spot-check"):
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            out.setdefault(r["key"], [])
            if r["candidate"] not in out[r["key"]]:
                out[r["key"]].append(r["candidate"])
    return out


def save(path, labels):
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp") as f:
        f.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in labels))
        f.flush()
        os.fsync(f.fileno())
    os.replace(f.name, path)


def show(col, t, label):
    with col.container(border=True):
        st.caption(label)
        st.subheader(f"{t.get('key')} · {t.get('issuetype', '')}")
        st.markdown(f"**{t.get('summary', '(missing)')}**")
        st.write(", ".join(t.get("components") or []) or "")
        st.text((t.get("description") or "")[:2500])


def main():
    st.set_page_config(page_title="Assay | Blind labels", layout="wide")
    path = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("ASSAY_LABELS", ""))
    if not path.is_file():
        st.error("Pass a worksheet: streamlit run app/label_app.py -- results/stage-2-3-runs/<name>-labels.jsonl")
        return
    labels = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    by, lists = tickets(), shortlists()
    todo = [i for i, r in enumerate(labels) if r.get("correct") is None and r.get("label_status") != "skipped"]
    with st.sidebar:
        st.title("Blind labels")
        reviewer = st.text_input("Your name", key="reviewer")
        st.metric("Left to label", len(todo))
        st.metric("Done", sum(r.get("correct") is not None for r in labels))
        st.caption(f"{path.name} · maintainer-link prefills: {sum(r.get('reviewer') == 'maintainer-link' for r in labels)}")
        st.caption("You never see the model's confidence, prompt or model. Judge the tickets only.")
    if not todo:
        st.success("Everything in this worksheet is labelled.")
        return
    i = todo[0]
    r = labels[i]
    new = by.get(r["key"], {"key": r["key"]})
    if r["relation"] == "none":
        st.header(f"Is {r['key']} a duplicate of, part of, or related to ANY of these earlier tickets?")
        st.caption("The agent proposed no link. It is right only if none of them really relates.")
        show(st, new, "NEW ticket")
        for c in lists.get(r["key"], []):
            show(st, by.get(c, {"key": c}), "Earlier candidate")
        question = "The agent said: no link. Correct?"
    else:
        st.header(f"Proposed: {r['key']} is **{r['relation'].replace('_', ' ')}** {r['candidate']}")
        left, right = st.columns(2)
        show(left, new, "NEW ticket")
        show(right, by.get(r["candidate"], {"key": r["candidate"]}), "Earlier candidate")
        question = f"Is {r['key']} really {r['relation'].replace('_', ' ')} {r['candidate']}?"
    reason = st.text_input("Short reason (optional)", key=f"reason-{i}")
    a, b, c = st.columns(3)
    choice = None
    if a.button(f"✅ Yes: {question}", use_container_width=True):
        choice = True
    if b.button("❌ No, wrong", use_container_width=True):
        choice = False
    if c.button("🤷 Can't tell (stays unknown)", use_container_width=True):
        choice = "skip"
    if choice is not None:
        if not reviewer.strip():
            st.warning("Enter your name in the sidebar first.")
            return
        if choice == "skip":
            labels[i] = {**r, "label_status": "skipped", "reviewer": reviewer.strip(), "reason": reason}
        else:
            labels[i] = {**r, "correct": choice, "reviewer": reviewer.strip(), "reason": reason,
                         "label_status": "adjudicated"}
        save(path, labels)
        st.rerun()


if __name__ == "__main__":
    main()
