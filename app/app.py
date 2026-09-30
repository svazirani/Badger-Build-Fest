"""Assay Triage: the reviewer-facing app.

    streamlit run app/app.py

Pages: Review queue (home), Trust, Try a ticket, Model check. Data contract: docs/SCHEMA.md.
Importing this module has no side effects; the UI only runs under `streamlit run` (or AppTest).
"""
from __future__ import annotations

import html
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import app_data as D  # noqa: E402

PAGES = ("Review queue", "Trust", "Try a ticket", "Model check")
PAGE_SIZE = 10
BAND_TEXT = {"auto": "Acts on its own", "suggest": "Asks a reviewer", "silent": "Stays quiet"}

CSS = """
<style>
.at-chip{display:inline-block;padding:2px 10px;border-radius:999px;font-size:0.8rem;font-weight:600;
  white-space:nowrap;border:1px solid transparent}
.at-duplicate{background:rgba(220,80,60,.14);color:#c0392b;border-color:rgba(220,80,60,.35)}
.at-part_of{background:rgba(120,90,220,.14);color:#6c4fd1;border-color:rgba(120,90,220,.35)}
.at-related{background:rgba(40,130,200,.14);color:#1f78b4;border-color:rgba(40,130,200,.35)}
.at-none{background:rgba(128,128,128,.14);color:#777;border-color:rgba(128,128,128,.35)}
.at-auto{background:rgba(30,160,90,.15);color:#178a4c;border-color:rgba(30,160,90,.4)}
.at-suggest{background:rgba(230,160,20,.16);color:#a86b00;border-color:rgba(230,160,20,.45)}
.at-silent{background:rgba(128,128,128,.14);color:#777;border-color:rgba(128,128,128,.35)}
.at-ticket .at-key{font-size:.8rem;opacity:.75;letter-spacing:.02em}
.at-ticket .at-sum{font-weight:600;margin:2px 0 4px 0;line-height:1.3}
.at-ticket .at-desc{font-size:.85rem;opacity:.8;line-height:1.4}
.at-label{font-size:.7rem;text-transform:uppercase;letter-spacing:.08em;opacity:.6}
.at-mid{text-align:center;padding-top:1.4rem}
.at-conf{font-size:.8rem;opacity:.75;margin-top:6px}
.at-reason{font-style:italic;opacity:.9;margin:.2rem 0 .4rem 0}
.at-table{width:100%;border-collapse:collapse;font-size:.9rem}
.at-table th{text-align:left;font-weight:600;opacity:.7;font-size:.75rem;text-transform:uppercase;letter-spacing:.05em}
.at-table td,.at-table th{padding:6px 8px;border-bottom:1px solid rgba(128,128,128,.2)}
.at-sample{background:rgba(230,160,20,.18);border:1px dashed rgba(230,160,20,.8);padding:6px 12px;
  border-radius:8px;font-weight:600;margin-bottom:.8rem}
</style>
"""


# ---------------------------------------------------------------- small helpers (pure, testable)

def clean(text: str | None, n: int = 300) -> str:
    """First ~n chars of a Jira description with the wiki markup noise removed."""
    t = re.sub(r"\{(code|noformat|quote|panel)[^}]*\}", " ", text or "")
    t = re.sub(r"\{color[^}]*\}|h[1-6]\.\s|\[~[^\]]+\]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t if len(t) <= n else t[: n - 1].rsplit(" ", 1)[0] + "…"


def chip(text: str, cls: str) -> str:
    return f'<span class="at-chip at-{cls}">{html.escape(text)}</span>'


def ticket_html(t: dict | None, key: str, label: str) -> str:
    url = D.ticket_url(key)
    k = html.escape(key)
    key_html = f'<a href="{url}" target="_blank">{k}</a>' if url else k
    if t is None:
        return (f'<div class="at-ticket"><div class="at-label">{label}</div><div class="at-key">{key_html}</div>'
                f'<div class="at-desc">(ticket text not in tickets.jsonl)</div></div>')
    meta = " · ".join(x for x in [t.get("issuetype"), ", ".join(t.get("components") or []), (t.get("created") or "")[:10]] if x)
    return (f'<div class="at-ticket"><div class="at-label">{label}</div>'
            f'<div class="at-key">{key_html} · {html.escape(meta)}</div>'
            f'<div class="at-sum">{html.escape(t.get("summary") or "")}</div>'
            f'<div class="at-desc">{html.escape(clean(t.get("description")))}</div></div>')


def pct(x: float | None, digits: int = 0) -> str:
    return "–" if x is None else f"{100 * x:.{digits}f}%"


def current_user(st) -> str:
    try:
        h = st.context.headers  # Databricks Apps forwards the signed-in user's identity in these headers
        u = h.get("X-Forwarded-Email") or h.get("X-Forwarded-Preferred-Username")
        if u:
            return u
    except Exception:
        pass
    return os.environ.get("ASSAY_USER") or os.environ.get("USER") or "reviewer"


# ---------------------------------------------------------------- cached loaders

def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def make_loaders(st):
    @st.cache_data(show_spinner=False)
    def jsonl(path: str, mtime: float) -> list[dict]:
        return D.load_jsonl(Path(path))

    @st.cache_data(show_spinner=False)
    def tickets_by_key(path: str, mtime: float) -> dict:
        return {t["key"]: t for t in D.load_jsonl(Path(path)) if "key" in t}

    @st.cache_resource(show_spinner=False)
    def local_index(path: str, mtime: float):
        rows = D.load_jsonl(Path(path))
        return D.LocalIndex(rows) if rows else None

    def load(dir_: Path, name: str):
        p = dir_ / name
        return jsonl(str(p), _mtime(p))

    def tickets(dir_: Path) -> dict:
        p = dir_ / "tickets.jsonl"
        return tickets_by_key(str(p), _mtime(p))

    def index(dir_: Path):
        p = dir_ / "tickets.jsonl"
        return local_index(str(p), _mtime(p))

    return load, tickets, index


# ---------------------------------------------------------------- pages

def page_queue(st, ctx):
    st.title("Review queue")
    J, B = ctx["judgments"], ctx["bands"]
    if not J:
        st.info("No judgments yet: run `scripts/judge.py` to have the agent look at new tickets"
                + ("" if ctx["sample"] else ", or switch on **Use sample data** in the sidebar to explore.") )
        return
    auto = D.auto_handled(J, B, ctx["model"])
    if auto["proven"] is not None:
        st.markdown(f"Handled automatically today: **{auto['today']}** "
                    f"(proven precision ≥ {pct(auto['proven'])}) · {auto['total']} in all")
    else:
        st.markdown(f"Handled automatically today: **0**. No relation has proven precision "
                    f"≥ {pct(D.AUTO_TARGET)} yet, so every proposal comes here first.")

    q = D.queue(J, ctx["feedback"], B, ctx["model"])
    flash = st.session_state.pop("flash", None)
    if flash:
        st.success(flash)
    if not q:
        st.success("Nothing waiting for review.")
        return

    counts = {r: sum(1 for j in q if j["relation"] == r) for r in D.RELATIONS}
    opts = ["All"] + [r for r in D.RELATIONS if counts[r]]
    show = st.radio("Show", opts, horizontal=True, label_visibility="collapsed",
                    format_func=lambda r: f"All ({len(q)})" if r == "All" else f"{D.LABEL[r]} ({counts[r]})")
    if show != "All":
        q = [j for j in q if j["relation"] == show]
    n = st.session_state.setdefault("show_n", PAGE_SIZE)
    for j in q[:n]:
        card(st, ctx, j)
    if len(q) > n:
        st.button(f"Show {min(PAGE_SIZE, len(q) - n)} more", on_click=lambda: st.session_state.update(show_n=n + PAGE_SIZE))


def _record(st, ctx, j: dict, decision: str, new_relation: str | None = None):
    row = D.make_feedback(j["key"], j["candidate"], j["relation"], decision, new_relation, ctx["user"])
    D.append_feedback(ctx["dir"], row)
    verb = {"accept": "Accepted", "reject": "Rejected", "change": "Changed"}[decision]
    extra = f" to {D.LABEL[new_relation].lower()}" if new_relation else ""
    st.session_state["flash"] = f"{verb}{extra}: {j['key']} → {j['candidate']}. Thanks, this is how the agent earns trust."


def card(st, ctx, j: dict):
    t = ctx["tickets"]
    rel, pair = j["relation"], f"{j['key']}-{j['candidate']}"
    with st.container(border=True):
        left, mid, right = st.columns([5, 2, 5])
        left.markdown(ticket_html(t.get(j["key"]), j["key"], "New ticket"), unsafe_allow_html=True)
        mid.markdown(f'<div class="at-mid">{chip(D.LABEL[rel], rel)}<div class="at-conf">'
                     f'{pct(j.get("confidence"))} sure</div></div>', unsafe_allow_html=True)
        right.markdown(ticket_html(t.get(j["candidate"]), j["candidate"], "Earlier ticket"), unsafe_allow_html=True)
        if j.get("reason"):
            st.markdown(f'<div class="at-reason">“{html.escape(j["reason"])}”</div>', unsafe_allow_html=True)
        b1, b2, b3, _ = st.columns([1, 1, 1.6, 3])
        b1.button("Accept", key=f"acc-{pair}", type="primary", on_click=_record, args=(st, ctx, j, "accept"))
        b2.button("Reject", key=f"rej-{pair}", on_click=_record, args=(st, ctx, j, "reject"))
        with b3.popover("Change relation"):
            others = [r for r in D.ALL_RELATIONS if r != rel]
            new = st.radio("The right relation is", others, key=f"new-{pair}",
                           format_func=lambda r: D.LABEL[r])
            st.button("Save", key=f"chg-{pair}", on_click=_record, args=(st, ctx, j, "change", new))


def page_trust(st, ctx):
    st.title("Trust")
    st.caption(f"The agent acts on its own only where its precision is proven ≥ {pct(D.AUTO_TARGET)} "
               f"(one-sided 95% lower bound). Everything else goes to a reviewer or stays quiet.")
    ev = ctx["evidence"]
    if not ev:
        st.info("No judgments with a known answer yet: run `scripts/judge.py` on the evaluation tickets "
                "(rows need `correct`), or review a few suggestions in the queue.")
        return
    n_review = sum(1 for r in ev if r.get("truth_source") == "review")
    st.markdown(f"Based on **{len(ev) - n_review}** judgments checked against maintainers' own links"
                f" and **{n_review}** reviews in this app.")
    for rel in D.RELATIONS:
        b = ctx["bands"][rel]
        with st.container(border=True):
            st.subheader(D.PLURAL[rel].capitalize())
            if not b["n"]:
                st.caption("No labelled examples yet.")
                continue
            rows = "".join(
                f"<tr><td>{chip(s['band'], s['band'])}</td><td>{BAND_TEXT[s['band']]}</td>"
                f"<td>{s['lo']:.2f} – {s['hi']:.2f}</td><td>{pct(s['precision'], 1)}</td>"
                f"<td>{pct(s['lower'], 1)}</td><td>{s['n']}</td></tr>" for s in b["segments"])
            st.markdown('<table class="at-table"><tr><th>Band</th><th>What it does</th><th>Confidence</th>'
                        f'<th>Precision</th><th>Proven ≥</th><th>n</th></tr>{rows}</table>', unsafe_allow_html=True)
            sentence = D.trust_sentence(ev, rel)
            if sentence:
                st.caption(sentence)
            if b["auto_threshold"] is None:
                u = D.reviews_to_unlock(ev, rel)
                if u.get("more"):
                    st.markdown(f"Need **~{u['more']} more reviews** to unlock auto for {D.PLURAL[rel]} "
                                f"(at today's {pct(u['precision'], 1)} hit rate on calls ≥ {D.TOP_CONF:.1f} confidence).")
                elif u.get("n"):
                    st.markdown(f"Auto stays off for {D.PLURAL[rel]}: confident calls are right "
                                f"{pct(u['precision'], 1)} of the time, below the {pct(D.AUTO_TARGET)} bar.")
    st.caption(f"Computed by {ctx['bands']['duplicate']['source']}. Model: {ctx['model'] or '–'}.")


def _search(st, ctx, text: str, k: int) -> list[dict]:
    fn = None if ctx["sample"] or os.environ.get("ASSAY_DATA_DIR") else D.engine("search", "assay_triage.retrieve")
    if fn is not None:
        try:
            return fn(text, k)
        except Exception:
            pass
    idx = ctx["index"]
    return idx.search(text, k) if idx is not None else []


def _judge_backend() -> tuple[str, str]:
    default_backend = ("openai" if os.environ.get("OPENAI_API_KEY") else
                       "databricks" if os.environ.get("DATABRICKS_HOST") else "cli")
    backend = os.environ.get("ASSAY_JUDGE_BACKEND") or default_backend
    default_model = (os.environ.get("OPENAI_MODEL", "gpt-5-mini") if backend == "openai" else
                     "databricks-claude-haiku-4-5" if backend == "databricks" else "haiku")
    model = os.environ.get("ASSAY_JUDGE_MODEL") or default_model
    if backend == "databricks" and not os.environ.get("DATABRICKS_TOKEN"):
        try:  # inside a Databricks App: borrow the app's own OAuth token from the SDK
            from databricks.sdk import WorkspaceClient
            w = WorkspaceClient()
            os.environ["DATABRICKS_HOST"] = w.config.host  # the SDK's form always carries https://
            os.environ["DATABRICKS_TOKEN"] = w.config.authenticate()["Authorization"].split(" ", 1)[1]
        except Exception:
            pass
    return backend, model


def page_try(st, ctx):
    st.title("Try a ticket")
    st.caption("Paste a new ticket. The agent finds earlier tickets it might duplicate, belong to, or relate to.")
    tickets = ctx["tickets"]
    if not tickets:
        st.info("No tickets yet: run `python -m assay_triage.ingest` to fetch Apache Jira tickets"
                + ("" if ctx["sample"] else ", or switch on **Use sample data**."))
        return
    with st.form("try_form"):
        title = st.text_input("Title", placeholder="e.g. NPE in DataFrame.join when the right side is empty")
        desc = st.text_area("Description", height=140, placeholder="What happened, steps to reproduce, versions…")
        go = st.form_submit_button("Find related tickets", type="primary")
    if go:
        if not title.strip():
            st.warning("Give the ticket a title first.")
            return
        st.session_state["try_state"] = {"title": title, "desc": desc,
                                   "hits": _search(st, ctx, f"{title} {title} {desc}", 5), "verdicts": None}
    state = st.session_state.get("try_state")
    if not state:
        return
    hits = state["hits"]
    if not hits:
        st.info("No earlier ticket looks similar.")
        return
    judge = D.engine("judge", "assay_triage.judge")
    if judge is not None and st.button("Ask the agent about the top 3"):
        backend, model = _judge_backend()
        new = {"key": "NEW-1", "summary": state["title"], "description": state["desc"], "issuetype": "Bug",
               "components": []}
        cands = [tickets[h["key"]] for h in hits[:3] if h["key"] in tickets]
        with st.spinner(f"Asking {model}…"):
            try:
                state["verdicts"] = {r["candidate"]: r for r in judge(new, cands, model, backend)}
            except Exception as e:
                st.error(f"The judge could not be reached ({backend}/{model}): {str(e)[:200]}")
    elif judge is None:
        st.caption("Verdicts appear here once `assay_triage.judge` is available.")
    for h in hits:
        t = tickets.get(h["key"])
        with st.container(border=True):
            c1, c2 = st.columns([7, 3])
            c1.markdown(ticket_html(t, h["key"], f"Similarity {h['score']:.2f}"), unsafe_allow_html=True)
            v = (state.get("verdicts") or {}).get(h["key"])
            if v:
                band = D.band_of(ctx["bands"][v["relation"]], v["confidence"]) if v["relation"] in D.RELATIONS else "silent"
                c2.markdown(f'<div class="at-mid">{chip(D.LABEL[v["relation"]], v["relation"])}'
                            f'<div class="at-conf">{pct(v["confidence"])} sure</div>'
                            f'<div class="at-conf">{chip(BAND_TEXT[band], band)}</div></div>', unsafe_allow_html=True)
                if v.get("reason"):
                    st.markdown(f'<div class="at-reason">“{html.escape(v["reason"])}”</div>', unsafe_allow_html=True)


def page_models(st, ctx):
    st.title("Model check")
    st.caption("Can a cheaper model do this step just as well? Both models judge the same tickets; "
               "the verdict holds only if the quality drop is proven small and the saving is real.")
    comps = D.normalise_compare(D.load_json(ctx["dir"] / "model_compare.json"))
    if not comps:
        st.info("No model comparison yet: run the comparison script to write `data/model_compare.json`.")
    for c in comps:
        v = str(c.get("verdict")).upper()
        cls = {"CERTIFY": "auto", "REJECT": "duplicate"}.get(v, "suggest")
        with st.container(border=True):
            st.markdown(f"{chip(v, cls)}", unsafe_allow_html=True)
            st.markdown(f"**{html.escape(D.compare_headline(c))}**")
            m1, m2, m3 = st.columns(3)
            if c.get("quality_pp") is not None:
                m1.metric("Quality change", f"{c['quality_pp']:+.1f} pts",
                          help=f"one-sided bounds [{c.get('quality_lo_pp', 0):+.1f}, {c.get('quality_hi_pp', 0):+.1f}]")
            if c.get("cost_rel") is not None:
                m2.metric("Cost change", f"{100 * c['cost_rel']:+.0f}%")
            m3.metric("Tickets compared", c.get("n", "–"))
            if c.get("reason"):
                more = c.get("need_n")
                more = "" if not more else (f"; ~{more} more tickets needed" if more <= 20 * max(c.get("n") or 1, 1)
                                            else "; far more data needed to tell")
                st.caption(c["reason"] + more)
    models = sorted({j.get("model") for j in ctx["all_judgments"] if j.get("model") and j.get("correct") is not None})
    if len(models) >= 2 and D.engine("compare_models") is not None:
        with st.expander("Compare two models now"):
            a = st.selectbox("Current model", models, index=len(models) - 1)
            b = st.selectbox("Cheaper model", [m for m in models if m != a])
            if st.button("Run the check"):
                res = D.compare_from_judgments(ctx["all_judgments"], a, b)
                if res is None:
                    st.warning("These two models have no tickets in common yet.")
                else:
                    st.markdown(f"**{html.escape(D.compare_headline(D.normalise_compare(res)[0]))}**")


# ---------------------------------------------------------------- main

def main():
    import streamlit as st

    st.set_page_config(page_title="Assay Triage", page_icon=":material/call_split:", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    load, tickets_of, index_of = make_loaders(st)

    @st.cache_resource(show_spinner="Loading data from Unity Catalog…")
    def _sync_once():
        return D.sync_from_volume()
    _sync_once()

    with st.sidebar:
        st.markdown("### Assay Triage")
        page = st.radio("Page", PAGES, label_visibility="collapsed")
        st.divider()
        has_real = D.has_data(D.REAL_DIR, "judgments.jsonl") or D.has_data(D.REAL_DIR, "tickets.jsonl")
        sample = st.toggle("Use sample data", value=not has_real,
                           help="Fake tickets and judgments from app/sample_data.py, kept in data/sample/.")
        if sample:
            from sample_data import ensure
            ensure(D.SAMPLE_DIR)
        dir_ = D.data_dir(sample)
        all_j = load(dir_, "judgments.jsonl")
        models = sorted({j.get("model") for j in all_j if j.get("model")})
        model = D.pick_model(all_j)
        if len(models) > 1:
            model = st.selectbox("Model", models, index=models.index(model))
        user = current_user(st)
        st.caption(f"Signed in as {user}")

    if sample:
        st.markdown('<div class="at-sample">SAMPLE DATA: fake tickets and fake model output for demo purposes. '
                    'Turn off "Use sample data" for the real Apache Jira results.</div>', unsafe_allow_html=True)

    J = [j for j in all_j if not model or j.get("model") == model]
    feedback = load(dir_, "feedback.jsonl")
    ev = D.evidence(J, feedback)
    ctx = {"sample": sample, "dir": dir_, "model": model, "user": user, "all_judgments": all_j, "judgments": J,
           "feedback": feedback, "evidence": ev, "bands": D.all_bands(ev), "tickets": tickets_of(dir_),
           "index": None}
    if page == "Try a ticket":
        ctx["index"] = index_of(dir_)
    {"Review queue": page_queue, "Trust": page_trust, "Try a ticket": page_try, "Model check": page_models}[page](st, ctx)


if __name__ == "__main__":
    main()
