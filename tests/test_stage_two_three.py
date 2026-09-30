import copy
import json
import subprocess
import sys
from datetime import datetime, timezone

import pytest

from assay_engine.learning import build_gate
from assay_engine.permissions import build_receipt, can_act, validate_receipt
from assay_engine.policy import label_template, select_action
from assay_triage.judge import configuration, openai_cost
from assay_triage.plans import freeze_stream, validate
from assay_triage.retrieve import all_candidates


def rows(config, plan="plan-1", outcomes=None):
    outcomes = outcomes or [("A", "X", "duplicate", .99), ("B", "Y", "related", .96)]
    result = []
    for key, candidate, relation, confidence in outcomes:
        result.append({"key": key, "candidate": candidate, "relation": relation,
                       "confidence": confidence, "config_id": config, "plan_id": plan,
                       "run_id": key + config, "parsed": True, "task_status": "complete"})
    return result


def adjudicate(judgments, config, answers):
    labels = label_template(judgments, config)
    for label in labels:
        label.update(correct=answers[label["key"]], reviewer="blind-reviewer",
                     reason="independently checked", label_status="adjudicated")
    return labels


def test_policy_selects_one_action_and_abstains():
    rs = rows("c", outcomes=[("A", "Z", "related", .9), ("A", "B", "duplicate", .9)])
    action = select_action(rs)
    assert action["candidate"] == "B" and action["relation"] == "duplicate"
    abstain = select_action([{**rs[0], "relation": "none"}])
    assert abstain["relation"] == "none" and abstain["candidate"] is None
    with pytest.raises(ValueError):
        select_action([rs[0], {**rs[1], "config_id": "different"}])


def test_permission_receipt_controls_family_and_fails_closed():
    config = "cfg"
    judgments = rows(config, outcomes=[(f"T{i}", f"C{i}", "duplicate", .99) for i in range(60)])
    labels = adjudicate(judgments, config, {f"T{i}": True for i in range(60)})
    receipt = build_receipt(judgments, labels, config, computed_at="2026-09-26T12:00:00+00:00")
    duplicate = receipt["decisions"][0]
    assert duplicate["alpha"] == pytest.approx(.05 / 3)
    assert duplicate["mode"] == "auto" and duplicate["lower"] >= .90
    assert receipt["decisions"][1]["mode"] == "suggest"
    assert can_act(receipt, "duplicate", .99, config, "2026-09-26T12:30:00+00:00")[0] == "auto"
    assert can_act(receipt, "duplicate", .99, "wrong", "2026-09-26T12:30:00+00:00")[0] == "suggest"
    assert can_act(receipt, "duplicate", .90, config, "2026-09-26T12:30:00+00:00")[0] == "suggest"
    assert can_act(receipt, "duplicate", .99, config, "2026-09-28T12:30:00+00:00")[0] == "suggest"
    bad = copy.deepcopy(receipt); bad["decisions"][0]["n"] = 999
    with pytest.raises(ValueError): validate_receipt(bad)


def test_unknown_labels_never_grant_permission():
    config = "cfg"
    judgments = rows(config, outcomes=[(f"T{i}", f"C{i}", "duplicate", .99) for i in range(100)])
    labels = label_template(judgments, config)
    receipt = build_receipt(judgments, labels, config)
    decision = receipt["decisions"][0]
    assert decision["mode"] == "suggest" and decision["n"] == 0
    assert decision["excluded"]["unknown_or_missing_label"] == 100


def test_part_of_permission_deduplicates_umbrella():
    config = "cfg"
    judgments = rows(config, outcomes=[(f"T{i}", "SAME-UMBRELLA", "part_of", .99) for i in range(80)])
    labels = adjudicate(judgments, config, {f"T{i}": True for i in range(80)})
    receipt = build_receipt(judgments, labels, config, computed_at="2026-09-27T08:00:00+00:00")
    decision = receipt["decisions"][1]
    assert decision["n"] == 1 and decision["mode"] != "auto"
    assert decision["excluded"]["dependent_sibling_action"] == 79
    assert can_act(receipt, "part_of", .99, config, "2026-09-27T08:30:00+00:00")[0] == "suggest"


def test_correlated_output_attack_fails_closed():
    config = "break-1"
    judgments = rows(config, outcomes=[("ONE-TASK", f"ACTION-{i}", "duplicate", .99) for i in range(50)])
    labels = adjudicate(judgments, config, {"ONE-TASK": True})
    receipt = build_receipt(judgments, labels, config, computed_at="2026-09-27T08:00:00+00:00")
    duplicate = receipt["decisions"][0]
    assert duplicate["n"] == duplicate["k"] == 1
    assert duplicate["mode"] == "suggest" and duplicate["lower"] < .90
    assert can_act(receipt, "duplicate", .99, config, "2026-09-27T08:30:00+00:00")[0] == "suggest"


def test_independent_control_can_earn_permission():
    config = "break-1"
    judgments = rows(config, outcomes=[(f"TASK-{i}", f"ACTION-{i}", "duplicate", .99) for i in range(50)])
    labels = adjudicate(judgments, config, {f"TASK-{i}": True for i in range(50)})
    receipt = build_receipt(judgments, labels, config, computed_at="2026-09-27T08:00:00+00:00")
    duplicate = receipt["decisions"][0]
    assert duplicate["n"] == duplicate["k"] == 50
    assert duplicate["mode"] == "auto" and duplicate["lower"] >= .90
    assert can_act(receipt, "duplicate", .99, config, "2026-09-27T08:30:00+00:00")[0] == "auto"


def test_exact_learning_gate_and_same_plan_requirement():
    before_id, after_id = "before", "after"
    before = rows(before_id, outcomes=[(f"T{i}", f"B{i}", "duplicate", .99) for i in range(20)])
    after = rows(after_id, outcomes=[(f"T{i}", f"A{i}", "duplicate", .99) for i in range(20)])
    labels = adjudicate(before, before_id, {f"T{i}": False for i in range(20)})
    labels += adjudicate(after, after_id, {f"T{i}": i < 10 for i in range(20)})
    gate = build_gate(before, after, labels, before_id, after_id)
    assert gate["verdict"] == "KEEP" and gate["fixed"] == 10 and gate["broke"] == 0
    assert gate["alpha"] == .025 and "lower" not in gate
    changed = copy.deepcopy(after); changed[0]["plan_id"] = "other"
    with pytest.raises(ValueError): build_gate(before, changed, labels, before_id, after_id)


def test_stream_plan_is_outcome_blind_disjoint_and_hashed():
    tickets = [{"key": "OLD", "created": "2024-01-01", "summary": "old"}]
    candidates = []
    for i in range(12):
        key = f"T{i}"
        tickets.append({"key": key, "created": "2025-01-01", "summary": f"Upgrade lib {i}"})
        candidates.append({"key": key, "candidates": [{"key": "OLD", "score": .8}]})
    first = freeze_stream(tickets, candidates, n=5, seed=1, min_score=.7)
    second = freeze_stream(tickets, candidates, n=5, seed=2, min_score=.7,
                           excluded={j["key"] for j in first["jobs"]})
    assert not ({j["key"] for j in first["jobs"]} & {j["key"] for j in second["jobs"]})
    assert "truth" not in first["jobs"][0] and validate(first) == first
    bad = copy.deepcopy(first); bad["min_top_score"] = .1
    with pytest.raises(ValueError): validate(bad)


def test_outcome_selected_sample_attack_and_honest_control():
    from scripts.break_2_manipulated_sample import build_break_result
    result = build_break_result(seeds=100)
    assert result["population"]["precision"] == .25
    assert result["enriched_attack"]["decision"] == "auto"
    assert result["outcome_blind_trials"]["false_auto"] == 0
    assert result["passed"]


def test_all_candidates_is_time_honest():
    tickets = [{"key":"A","created":"2024-01-01","summary":"same alpha","description":""},
               {"key":"B","created":"2025-01-01","summary":"same alpha","description":""},
               {"key":"C","created":"2026-01-01","summary":"same alpha","description":""}]
    result = all_candidates(tickets, k=2)
    assert [r["key"] for r in result] == ["B", "C"]
    assert all(item["key"] == "A" for item in result[0]["candidates"])


def test_frozen_runner_is_dry_by_default(tmp_path):
    plan = {"schema":2,"seed":1,"requested_n":0,"k":5,"eligible_n":0,"min_top_score":.2,
            "slice_pattern":None,"scope":"honest-stream-confirmation",
            "selection":"uniform", "injected":False,"limitations":[],"source_hashes":{},"jobs":[]}
    from assay_triage.identity import digest
    plan["plan_id"] = digest(plan)
    path = tmp_path / "plan.json"; path.write_text(json.dumps(plan))
    script = __import__('pathlib').Path(__file__).resolve().parents[1] / 'scripts' / 'run_frozen_eval.py'
    result = subprocess.run([sys.executable, str(script), '--plan', str(path), '--out', str(tmp_path/'out.jsonl'),
                             '--prompt', 'v2'], capture_output=True, text=True, check=True)
    assert '"model_calls": 0' in result.stdout and not (tmp_path/'out.jsonl').exists()


def test_stream_judge_uses_runner_configuration_and_rejects_partial_json(monkeypatch):
    from assay_triage import judge as module
    ticket = {"key": "NEW", "summary": "new", "description": "", "issuetype": "Bug"}
    candidates = [{"key": "OLD", "summary": "old", "description": "", "issuetype": "Bug"}]
    monkeypatch.setattr(module, "call", lambda *args, **kwargs: (
        '{"judgments":[{"candidate":"OLD","relation":"duplicate","confidence":0.99}]}', 0.1, {}))
    result = module.judge(ticket, candidates, "sonnet", prompt="v2", retrieval_k=5,
                          retrieval_version="stream-v1")
    assert result[0]["config_id"] == configuration("sonnet", "cli", "v2", 5, "stream-v1")["config_id"]
    monkeypatch.setattr(module, "call", lambda *args, **kwargs: ('{"judgments":[]}', 0.1, {}))
    with pytest.raises(RuntimeError, match="Incomplete or invalid"):
        module.judge(ticket, candidates, "sonnet", prompt="v2", retrieval_k=5,
                     retrieval_version="stream-v1")


def test_openai_cost_uses_cached_input_and_output_prices():
    usage = {"input_tokens": 10_000, "input_tokens_details": {"cached_tokens": 4_000},
             "output_tokens": 2_000}
    expected = (6_000 * .25 + 4_000 * .025 + 2_000 * 2.0) / 1_000_000
    assert openai_cost("gpt-5-mini", usage) == pytest.approx(expected)
    assert openai_cost("unknown-model", usage) is None


def test_label_key_dedupes_across_configs_and_truth_prefill():
    from assay_engine.policy import prefill_from_truth, scored_actions
    def rows(cfg, conf):
        return [dict(key='T-2', candidate='T-1', relation='duplicate', confidence=conf, config_id=cfg, parsed=True),
                dict(key='T-2', candidate='T-0', relation='none', confidence=.9, config_id=cfg, parsed=True),
                dict(key='T-9', candidate='T-3', relation='none', confidence=.9, config_id=cfg, parsed=True)]
    a, b = rows('v1', .7), rows('v2', .99)
    la, lb = label_template(a, 'v1'), label_template(b, 'v2')
    assert la[0]['action_id'] != lb[0]['action_id'] and la[0]['label_key'] == lb[0]['label_key']
    truth = [{'src': 'T-2', 'dst': 'T-1', 'relation': 'duplicate'}, {'src': 'T-9', 'dst': 'T-3', 'relation': 'related'}]
    labels = prefill_from_truth(la, a, truth)
    assert [l['correct'] for l in labels] == [True, False]  # linked duplicate confirmed; "none" contradicted by a link
    assert [s['correct'] for s in scored_actions(b, labels, 'v2')] == [True, False]  # one label serves both configs


def test_receipt_reports_needs_more():
    from assay_engine.permissions import build_receipt
    rows = [dict(key=f'K-{i}', candidate=f'C-{i}', relation='duplicate', confidence=.97, config_id='c', parsed=True)
            for i in range(10)]
    labels = [{**l, 'correct': True, 'reviewer': 't', 'label_status': 'adjudicated'} for l in label_template(rows, 'c')]
    dup = build_receipt(rows, labels, 'c')['decisions'][0]
    assert dup['mode'] == 'suggest' and dup['n'] == 10 and dup['needs_more'] > 0


def test_gate_counts_same_action_as_tie_without_labels():
    from assay_engine.learning import build_gate
    def rows(cfg, rel_for):
        return [dict(key=f'K-{i}', candidate=f'C-{i}', relation=rel_for(i), confidence=.9, config_id=cfg,
                     plan_id='p', parsed=True) for i in range(10)]
    before = rows('v1', lambda i: 'duplicate')
    after = rows('v2', lambda i: 'duplicate' if i < 6 else 'none')  # 6 identical actions, 4 changed
    labels = [{**l, 'correct': l['relation'] == 'none', 'reviewer': 't', 'label_status': 'adjudicated'}
              for l in label_template(before, 'v1')[6:] + label_template(after, 'v2')[6:]]
    g = build_gate(before, after, labels, 'v1', 'v2')
    assert (g['n_same_action'], g['fixed'], g['broke'], g['excluded_unknown'], g['unchanged']) == (6, 4, 0, 0, 6)


def test_router_switches_live_and_holds_untrusted_answers():
    from assay_engine.router import policy_from_evidence, route
    pol = policy_from_evidence('big', 'small', ['backup'], cheap_verdict='REJECT', cheap_evidence='right 4 of 19')
    calls = []
    def fake(ticket, cands, model, backend, prompt, retries=1):
        calls.append(model)
        if model == 'big':
            raise RuntimeError("Error code: 429 - REQUEST_LIMIT_EXCEEDED")
        return [{'model': model}]
    rows, d = route({'key': 'T-1'}, [], pol, judge_fn=fake)
    assert calls == ['big', 'backup'] and d['answered_by'] == 'backup' and d['switched'] and d['needs_review']
    assert 'not certified' in d['reason'] and 'busy' in d['reason']
    ok = policy_from_evidence('big', 'small', [], cheap_verdict='CERTIFY', cheap_evidence='certified')
    calls.clear()
    _, d2 = route({'key': 'T-2'}, [], ok, judge_fn=fake)
    assert calls == ['small'] and d2['answered_by'] == 'small' and d2['trusted'] and not d2['switched']
    def broken(ticket, cands, model, backend, prompt, retries=1):
        raise RuntimeError("Incomplete or invalid model JSON for candidates: X")
    _, d3 = route({'key': 'T-3'}, [], pol, judge_fn=broken)
    assert d3['answered_by'] is None and d3['needs_review'] and 'sent to a human' in d3['reason']


def test_precedent_reuse_only_when_proven_and_leave_one_out():
    from assay_engine.precedent import build_memory, case_kind, leave_one_out, resolve
    t = {}
    decisions = []
    for i in range(40):  # 40 same-library upgrade pairs to different versions, all rejected as duplicates
        a, b = f"N-{i}", f"E-{i}"
        t[a] = {"key": a, "summary": f"Upgrade jackson to 2.{i + 1}.0"}
        t[b] = {"key": b, "summary": f"Upgrade jackson to 2.{i}.0"}
        decisions.append({"id": a, "key": a, "candidate": b, "relation": "duplicate", "correct": False, "source": "ai"})
    assert case_kind(t["N-0"], t["E-0"]) == "bump-same-lib-diff-version"
    few = build_memory(decisions[:21], t, target=0.9)["duplicate/bump-same-lib-diff-version"]
    assert not few["enabled"] and few["needs_more"] == 8  # 21/21 is not yet proof at 90%
    mem = build_memory(decisions, t, target=0.9)
    r = resolve({"key": "X", "summary": "Upgrade jackson to 3.0.0"}, {"key": "Y", "summary": "Upgrade jackson to 2.9.0"},
                "duplicate", mem)
    assert r["mode"] == "auto-reject" and "40 of 40" in r["reason"]
    other = resolve({"key": "X", "summary": "Fix a crash"}, {"key": "Y", "summary": "Improve docs"}, "duplicate", mem)
    assert other["mode"] == "ask"
    loo = leave_one_out(decisions, t, target=0.9)
    assert loo["auto_resolved"] == 40 and loo["right"] == 40
