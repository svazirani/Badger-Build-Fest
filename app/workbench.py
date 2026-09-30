"""Stage-one local workbench. Recorded data only; no model client is imported."""
import json
import os
import sqlite3
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import streamlit as st
STORE = os.environ.get('ASSAY_STORE', 'local')  # 'delta' on Databricks: reviews + links in a Delta table
if STORE == 'delta':
    from assay_engine.delta_store import records, review, proposal_id, permission_status
else:
    from assay_engine.local_store import records, review, proposal_id, permission_status
from assay_triage.identity import legacy_config


RUN_FILES = ('permission-v2.jsonl', 'permission-v2-cheap.jsonl', 'gate-v1.jsonl', 'gate-v2.jsonl',
             'stress-v1.jsonl', 'stress-bad.jsonl')


def receipt_for(root, config):
    """Newest valid-looking permission receipt for this configuration (receipts are configuration-scoped)."""
    found = []
    for p in Path(root).glob('**/permission-*.json'):
        try:
            r = json.loads(p.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            continue
        if r.get('config_id') == config:
            found.append((p.stat().st_mtime_ns, r))
    return max(found, key=lambda x: x[0])[1] if found else None


@st.cache_data
def load_data(folder, stamp):
    def read(name):
        p = Path(folder) / name
        return [json.loads(line) for line in p.read_text(encoding='utf-8').splitlines() if line.strip()] if p.exists() else []
    runs = ROOT / 'results' / 'stage-2-3-runs'  # Databricks Stage 2/3 runs (one config per file)
    extra = [json.loads(line) for name in RUN_FILES if (runs / name).exists()
             for line in (runs / name).read_text(encoding='utf-8').splitlines() if line.strip()]
    return read('tickets.jsonl'), read('judgments.jsonl') + extra


def latest_json(root, pattern):
    matches = sorted(Path(root).glob(pattern), key=lambda p: p.stat().st_mtime_ns, reverse=True)
    if not matches:
        return None
    try:
        return json.loads(matches[0].read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None


@st.cache_resource
def fetch_volume(volume):
    """Databricks App: copy the input files from the Unity Catalog volume once per app start (files > 10 MB can't ship in the app)."""
    from assay_triage.dbx import client
    w, out = client(), Path('/tmp/assay-data')
    out.mkdir(parents=True, exist_ok=True)
    for name in ('tickets.jsonl', 'judgments.jsonl'):
        (out / name).write_bytes(w.files.download(f"{volume}/{name}").contents.read())
    return out


def main():
    st.set_page_config(page_title='Assay | Review workbench', page_icon='A', layout='wide')
    st.markdown('''<style>
    .stApp {background:#f6f8fb} .block-container {max-width:1250px;padding-top:2rem}
    h1,h2,h3 {color:#19374c} [data-testid="stSidebar"] {background:#e9f0f3}
    [data-testid="stMetric"] {background:white;border:1px solid #dce5eb;border-radius:12px;padding:16px}
    </style>''', unsafe_allow_html=True)
    folder = Path(os.environ.get('ASSAY_WORKBENCH_DATA', ROOT / 'data'))
    if os.environ.get('ASSAY_DATA_VOLUME'):
        folder = fetch_volume(os.environ['ASSAY_DATA_VOLUME'])
    db = Path(os.environ.get('ASSAY_WORKBENCH_DB', ROOT / 'local-state' / 'workbench.sqlite3'))
    result_dir = Path(os.environ.get('ASSAY_RESULTS_DIR', ROOT / 'results' / 'stage-2-3-runs'))
    stamp = tuple((folder / n).stat().st_mtime_ns if (folder/n).exists() else 0 for n in ['tickets.jsonl','judgments.jsonl'])
    tickets, rows = load_data(str(folder), stamp)
    by = {t['key']:t for t in tickets}
    configs = sorted({legacy_config(r) for r in rows})
    with st.sidebar:
        st.title('Assay')
        st.caption('Evidence before permission')
        page = st.radio('Workspace', ['Review queue','Trust','Try a ticket','Model check'])
        st.divider()
        names = {legacy_config(r): f"{r.get('model','unknown')} / {r.get('prompt','legacy')}" for r in rows}
        config = st.selectbox('Recorded configuration', configs, format_func=lambda x:names[x]) if configs else ''
        user = st.text_input('Reviewer', value='Local reviewer')
        if STORE == 'delta':
            st.caption('DATABRICKS · Unity Catalog\n\nReviews and links are written to the Delta table workspace.assay_triage.actions.\n\nRecorded evidence · no model calls')
        else:
            st.caption('LOCAL DEMO · one reviewer\n\nRecorded evidence · no model calls\n\nWrites affect this sandbox only.')
    selected = [r for r in rows if legacy_config(r) == config]
    try:
        reviews = records(db)
        links = records(db, 'links')
    except Exception as e:
        st.error(f'Storage unavailable. Actions are disabled ({type(e).__name__}: {str(e)[:200]}).')
        st.stop()
    scoped = [r for r in reviews if r['config_id'] == config]
    scoped_links = [r for r in links if r['config_id'] == config]
    st.caption('ASSAY / STAGE 1 / RECORDED APACHE JIRA DATA')
    st.title(page)
    if not rows:
        st.info('Add the handover tickets.jsonl and judgments.jsonl to data/ to begin. No examples are fabricated.')
        return
    if page == 'Review queue':
        st.write('Inspect an agent proposal. Your approval writes one link to the local sandbox.')
        a,b,c = st.columns(3)
        a.metric('Sandbox links written',len(scoped_links))
        b.metric('Reviews saved',len(scoped))
        c.metric('Automatic actions',0)
        st.info('AUTO is off. Existing results are diagnostic; your reviews do not automatically grant permission.')
        done = {r['id'] for r in scoped}
        unique = {proposal_id(r):r for r in selected if r.get('relation') in ['duplicate','part_of','related']}
        todo = [r for key,r in unique.items() if key not in done]
        relation = st.selectbox('Filter relation',['All','duplicate','part_of','related'])
        if relation != 'All': todo = [r for r in todo if r['relation']==relation]
        st.caption(f'{len(todo)} proposals waiting in this configuration. Confidence is hidden during review.')
        if todo:
            i = st.selectbox('Choose proposal', range(len(todo)), format_func=lambda i:f"{todo[i]['key']} → {todo[i]['candidate']} · {todo[i]['relation']}")
            row = todo[i]
            left,right = st.columns(2)
            for col,key,label in [(left,row['key'],'New ticket'),(right,row['candidate'],'Candidate')]:
                t=by.get(key,{})
                with col.container(border=True):
                    st.caption(label)
                    st.subheader(key)
                    st.write(t.get('summary','Ticket content unavailable'))
                    st.write((t.get('description') or '')[:1800])
            with st.form('review-'+proposal_id(row)):
                st.write('**Proposed relation:** '+row['relation'])
                decision = st.radio('Your decision',['Accept sandbox link','Reject','Suggest correction'],horizontal=True)
                correction = st.selectbox('Correction (used only for Suggest correction)',['none','duplicate','part_of','related'])
                reason=st.text_area('Review note')
                if st.form_submit_button('Save review', type='primary'):
                    try:
                        receipt,created=review(db,row,{'Accept sandbox link':'accept','Reject':'reject','Suggest correction':'correct'}[decision],user,reason,correction if decision=='Suggest correction' else None)
                        st.session_state['saved']='Saved. One sandbox link was written.' if receipt['decision']=='accept' else 'Review saved. No link was written.'
                        if not created: st.session_state['saved']='Already reviewed; no duplicate action was created.'
                        st.rerun()
                    except (ValueError, OSError, RuntimeError, sqlite3.Error) as e:
                        st.error(f'Review was not confirmed. Check storage before retrying: {e}')
        else: st.success('No proposals waiting in this filter.')
        if st.session_state.get('saved'): st.success(st.session_state.pop('saved'))
        with st.expander('Action receipts and saved reviews',expanded=bool(scoped)):
            st.dataframe(scoped,hide_index=True)
            st.download_button('Download review receipts',json.dumps(scoped,indent=2),file_name='assay-reviews.json',mime='application/json')
    elif page == 'Trust':
        receipt = receipt_for(result_dir, config)
        if receipt:
            st.success(f"Permission receipt {receipt['receipt_id'][:12]} · valid until {receipt['valid_until']}")
            st.dataframe([{k: d.get(k) for k in ('relation', 'mode', 'n', 'k', 'precision', 'lower', 'target', 'needs_more')}
                          for d in receipt['decisions']], hide_index=True)
            st.caption('n/k = labelled actions at the AUTO cutoff and how many were right; lower = one-sided lower bound on '
                       'precision (family-adjusted). AUTO needs lower >= target. needs_more = extra labelled actions if precision holds.')
            verdicts = Path(result_dir) / 'VERDICTS.md'
            if verdicts.exists():
                with st.expander('How these labels were made and audited (VERDICTS.md)'):
                    st.markdown(verdicts.read_text(encoding='utf-8'))
        else:
            st.info(permission_status(config)['reason'])
            st.dataframe([{'relation':r,'mode':'SUGGEST','permission':'Not validated','configuration':config} for r in ['duplicate','part_of','related']],hide_index=True)
        st.subheader('What needs to happen next')
        st.write('Freeze the action policy and quality target, collect an honest sample without inserted answers, and evaluate independent tasks. A later stage will issue version-scoped permission receipts.')
        st.warning('The imported hardness set balances classes and includes inserted targets. Its candidate pairs are not independent tasks.')
        st.metric('Distinct recorded tasks',len({r['key'] for r in selected}))
        st.caption('Legacy model settings are unknown. A new prompt/configuration needs its own evidence; no inherited permission is assumed.')
    elif page == 'Try a ticket':
        st.write('Search the recorded ticket library locally. This does not run an AI judge.')
        query=st.text_input('Ticket key or words from its title')
        if query.strip():
            terms=query.lower().split()
            hits=[t for t in tickets if all(w in (t['key']+' '+t.get('summary','')).lower() for w in terms)][:20]
            st.caption(f'{len(hits)} matches shown (maximum 20).')
            for t in hits:
                with st.expander(t['key']+' · '+t.get('summary','')):
                    st.write((t.get('description') or '')[:2500])
        st.button('Run fresh AI judgment — not enabled',disabled=True)
    else:
        st.warning('Cost certification is not enabled. The imported paired bootstrap can overstate certainty on small or identical outcomes.')
        st.write('Recorded cost allocations below are diagnostics, not current invoices or certified savings.')
        summary=[]
        for cid in configs:
            rs=[r for r in rows if legacy_config(r)==cid]
            costs=[r['cost_usd'] for r in rs if r.get('cost_usd') is not None]
            summary.append({'configuration':names[cid],'tasks':len({r['key'] for r in rs}),
                            'pair rows':len(rs),'recorded allocated USD':sum(costs) if costs else None,
                            'verdict':'NOT EVALUATED'})
        st.dataframe(summary,hide_index=True)
        st.subheader('Prepare the next experiment')
        st.code('.\\.venv\\Scripts\\python.exe scripts/prepare_eval.py --fresh --n 60 --seed 1 --save-plan results/frozen-plan.json',language='powershell')
        st.caption('This command freezes inputs only. It makes zero model calls and refuses to overwrite an existing plan.')
        gates = [latest_json(result_dir, '**/gate-v1-to-v2-latest.json'),
                 latest_json(result_dir, '**/gate-v1-to-bad-latest.json')]
        gates = [g for g in gates if g]
        st.subheader('Correction gates')
        if gates:
            st.dataframe([{k:g.get(k) for k in ('label','verdict','n_adjudicated','fixed','broke','excluded_unknown','p_keep','p_discard')}
                          for g in gates], hide_index=True)
        else:
            st.info('No adjudicated correction-gate receipts yet. Frozen plans and model outputs are still required.')


if __name__ == '__main__':
    main()
