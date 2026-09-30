"""Zero-call frozen experiment preparation. Deliberately has no execute option."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from assay_triage.plans import freeze, save, validate
from assay_triage.judge import configuration


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--data', type=Path, default=Path(__file__).resolve().parents[1] / 'data')
    ap.add_argument('--n', type=int, default=60)
    ap.add_argument('--k', type=int, default=5)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--fresh', action='store_true')
    ap.add_argument('--save-plan', type=Path)
    ap.add_argument('--plan-file', type=Path)
    ap.add_argument('--prompt', choices=['v1','v2','bad'], default='v1')
    ap.add_argument('--model', default='sonnet')
    a = ap.parse_args()
    if a.plan_file and (a.save_plan or a.fresh):
        ap.error('Loading a frozen plan cannot be combined with resampling or saving.')
    def load(name):
        p = a.data / name
        return [json.loads(s) for s in p.read_text(encoding='utf-8').splitlines() if s.strip()] if p.exists() else []
    if a.plan_file:
        plan = validate(json.loads(a.plan_file.read_text(encoding='utf-8')))
    else:
        excluded = {r['key'] for r in load('judgments.jsonl')} if a.fresh else set()
        plan = freeze(load('tickets.jsonl'), load('candidates.jsonl'), load('truth.jsonl'), a.n, a.seed, a.k, excluded)
        if a.save_plan:
            save(plan, a.save_plan)
    config = configuration(a.model, prompt=a.prompt, k=plan['k'])
    print(json.dumps({'plan_id':plan['plan_id'], 'config_id':config['config_id'],
                      'tasks':len(plan['jobs']), 'scope':plan['scope'],
                      'limitations':plan['limitations'], 'model_calls':0}, indent=2))


if __name__ == '__main__':
    main()
