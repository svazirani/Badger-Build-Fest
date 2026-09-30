import copy
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from assay_engine.local_store import review, records, permission_status
from assay_triage.judge import configuration, build_prompt, judge, call
from assay_triage.identity import resume_key
from assay_triage.plans import freeze, validate, pending, save


def test_atomic_duplicate_review_and_restart(tmp_path):
    db=tmp_path/'state.sqlite3'
    row=dict(key='A',candidate='B',relation='duplicate',model='test')
    with ThreadPoolExecutor(4) as pool:
        results=list(pool.map(lambda _:review(db,row,'accept','tester'),range(8)))
    assert sum(created for _,created in results)==1
    assert len(records(db,'links'))==len(records(db))==1
    assert not review(db,row,'reject','tester')[1]
    assert records(db)[0]['decision']=='accept'
    review(db,{**row,'config_id':'new'},'correct','tester',correction='none')
    assert len(records(db))==2 and len(records(db,'links'))==1


def test_unvalidated_permissions_and_call_guard(monkeypatch):
    assert not permission_status('legacy')['auto']
    assert not permission_status('v2')['auto']
    monkeypatch.delenv('ASSAY_ALLOW_MODEL_CALLS',raising=False)
    with pytest.raises(RuntimeError,match='disabled'): call('hello','model')


def test_storage_failure_does_not_claim_success(tmp_path):
    import sqlite3
    blocked=tmp_path/'not-a-database'
    blocked.mkdir()
    with pytest.raises(sqlite3.OperationalError):
        review(blocked,dict(key='A',candidate='B',relation='duplicate',model='test'),'accept','tester')


def test_prompt_identity_and_usage(monkeypatch):
    import assay_triage.judge as module
    ticket=dict(key='A',created='2025',summary='Example')
    candidate=dict(key='B',created='2024',summary='Earlier')
    assert build_prompt(ticket,[candidate],'v1') != build_prompt(ticket,[candidate],'v2')
    assert configuration('sonnet',prompt='v1')['config_id'] != configuration('sonnet',prompt='v2')['config_id']
    monkeypatch.setattr(module,'call',lambda *a: ('{"judgments":[{"candidate":"B","relation":"related","confidence":0.8}]}',.1,{'output_tokens':22}))
    rows=judge(ticket,[candidate],'sonnet',prompt='v2')
    assert rows[0]['usage']=={'output_tokens':22}
    assert rows[0]['prompt']=='v2' and rows[0]['task_cost_usd']==.1


def test_frozen_manifest_and_config_resume(tmp_path):
    ts=[dict(key='A',created='2025-01-01',summary='new'),dict(key='B',created='2024-01-01',summary='old'),dict(key='C',created='2026-01-01',summary='future')]
    plan=freeze(ts,[dict(key='A',candidates=[{'key':'B'},{'key':'C'}])],[],1)
    assert [t['key'] for t in plan['jobs'][0]['candidates']]==['B']
    assert plan['jobs'][0]['truth']['B']==[]
    path=tmp_path/'plan.json';save(plan,path)
    restored=validate(json.loads(path.read_text()))
    assert restored==plan
    with pytest.raises(FileExistsError):save(plan,path)
    bad=copy.deepcopy(plan);bad['jobs'][0]['ticket']['summary']='changed'
    with pytest.raises(ValueError):validate(bad)
    a=configuration('sonnet',prompt='v1');b=configuration('sonnet',prompt='v2')
    done=[{'status':'complete','run_id':resume_key('A',a['config_id'],plan['plan_id'])}]
    assert not pending(plan,a,done)
    assert len(pending(plan,b,done))==1
    done[0]['status']='failed'
    assert len(pending(plan,a,done))==1


def test_workbench_review_search_and_pages(tmp_path,monkeypatch):
    from streamlit.testing.v1 import AppTest
    data=tmp_path/'data';data.mkdir()
    tickets=[dict(key='A',created='2025',summary='Null pointer crash',description='A task'),dict(key='B',created='2024',summary='Earlier crash')]
    rows=[dict(key='A',candidate='B',relation='duplicate',model='sonnet',confidence=.99)]
    for name,items in [('tickets.jsonl',tickets),('judgments.jsonl',rows)]:
        (data/name).write_text('\n'.join(json.dumps(r) for r in items))
    monkeypatch.setenv('ASSAY_WORKBENCH_DATA',str(data))
    monkeypatch.setenv('ASSAY_WORKBENCH_DB',str(tmp_path/'state.sqlite3'))
    app=Path(__file__).resolve().parents[1]/'app'/'workbench.py'
    at=AppTest.from_file(str(app),default_timeout=30).run()
    assert not at.exception
    next(b for b in at.button if b.label=='Save review').click().run()
    assert not at.exception
    assert len(records(tmp_path/'state.sqlite3','links'))==1
    for page in ['Trust','Model check','Try a ticket','Review queue']:
        at.sidebar.radio[0].set_value(page).run()
        assert not at.exception
    at.sidebar.radio[0].set_value('Try a ticket').run()
    next(x for x in at.text_input if x.label=='Ticket key or words from its title').input('pointer').run()
    assert len(at.expander)==1
