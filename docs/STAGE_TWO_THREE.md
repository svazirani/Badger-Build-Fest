# Stages 2 and 3: evidence and correction gate

Status: the zero-cost implementation and outcome-blind input preparation are complete. Fresh model outputs and independent human adjudication are still required before any real permission or correction verdict exists.

## Locked defaults

- Permission target: 90% precision.
- Fixed AUTO confidence cutoff: 0.95, selected before confirmation outcomes.
- Error control: family alpha 0.05 split across duplicate, part_of and related.
- Unit: one deterministic highest-confidence non-none action per ticket. Ties use candidate key then relation. Part-of evidence retains one outcome-independent representative per predicted umbrella; its claim is across sampled predicted umbrellas.
- Missing labels are unknown and excluded. They never count as correct or incorrect.
- Correction family: v1-to-v2 and v1-to-bad, alpha 0.025 each. Exact paired sign tests report an observed change, not a confidence bound on effect size.
- Before/after configurations must use the same frozen plan. Failed or incomplete tasks do not silently become paired evidence.

## Prepared streams and plans

The local TF-IDF retrieval was run for all 16,919 tickets created since 2025-01-01. Top-score quantiles were q25 0.2242, q50 0.3085, q75 0.4575 and q90 0.6958. The q75 value was selected without model outcomes. It defines 4,231 eligible permission-stream tickets.

Disjoint plans in `results/stage-2-3-plans/`:

- permission: 90 tickets, seed 11, plan `5f17881a426f...`
- gate: 60 tickets, seed 23, plan `3c08f6a58ab...`
- version-update stress slice: 30 tickets, seed 37, plan `493344ca3a8e...`

The plans contain full ordered inputs and source hashes, no inserted targets and no truth fields. They are ignored by Git because they contain bulk public ticket text. Keep them with the local run artifacts or deliberately package them after team review.

## Human-run execution boundary

All commands below are dry runs unless `--execute --i-accept-usage` is supplied and `ASSAY_ALLOW_MODEL_CALLS=1`. Do not set that variable globally. Before execution, the human reviews the available OpenAI balance. Current plan: `gpt-5-mini` through the OpenAI Responses API, 270 paid calls:

- permission v2: 90 calls
- gate v1 and v2: 60 + 60 calls
- stress v1 and bad: 30 + 30 calls

The runner appends completed tasks with fsync, records failures separately and resumes only complete task/config/plan identities. It never converts failure into an abstention.

Dry-run example:

`.\.venv\Scripts\python.exe scripts\run_frozen_eval.py --plan results\stage-2-3-plans\permission.json --out results\stage-2-3-runs\permission-v2.jsonl --model gpt-5-mini --backend openai --prompt v2`

Put `OPENAI_API_KEY` in the ignored `.env` file. `Run-Stage23.ps1` loads the key, requires a specific 270-call confirmation, and enables model calls only for the duration of the run. OpenAI cost is calculated from returned input, cached-input and output usage using the official GPT-5 Mini list prices: $0.25, $0.025 and $2.00 per million tokens respectively.

## Independent adjudication

After outputs exist, create blinded action worksheets. Reviewers should not see model confidence or the competing version's correctness while labeling. The labels concern the selected action, including explicit no-action decisions. A maintainer link can establish a positive relation; the absence of a link is not automatically negative truth.

Permission worksheet:

`.\.venv\Scripts\python.exe scripts\label_actions.py --judgments results\stage-2-3-runs\permission-v2.jsonl --config b8d6ad23757d44cb6ba354ae4d1cdb3130094a04c1b9c197ea782186e95a450b --out results\stage-2-3-runs\permission-labels.jsonl`

For each row, the reviewer sets `correct` to true, false or null, adds their name and reason, and changes `label_status` to `adjudicated` or leaves it unknown. Validate before analysis with `--validate FILE`.

Gate worksheets combine both outputs with repeated `--judgments` and both configuration IDs. Do the same for the stress plan. Labels bind to action IDs, so a different model action receives a distinct adjudication.

## Receipts

`build_permissions.py` produces immutable configuration-scoped receipts. AUTO requires a valid, unexpired receipt, matching configuration and relation, confidence at least 0.95 and a family-adjusted lower bound of at least 0.90. Otherwise execution returns SUGGEST or QUIET. Unknown or dependent exclusions are reported.

`evaluate_correction.py` produces immutable KEEP, DISCARD or UNPROVEN receipts. It reports fixed and broken task IDs, paired sample size, unknown/dependent exclusions and exact p-values. The deliberately bad prompt is a stress test; DISCARD is not assumed in advance.

The local app automatically displays latest receipts placed below `results/stage-2-3-runs/`. Until outputs are run and adjudicated, it correctly shows no permission and no correction receipt.

## Remaining evidence requirement

Stages 2 and 3 are code-complete and input-ready, but not empirically complete. A real verdict requires 270 model calls and independent labels. The prior balanced hardness sample cannot substitute because it inserted targets and counted correlated candidate pairs. No model calls were made while building this stage.
