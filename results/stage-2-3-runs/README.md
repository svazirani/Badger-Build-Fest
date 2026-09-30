# Stage 2/3 runs on Databricks (Sat Sep 26, 18:05-18:20)

Backend: Databricks Foundation Model APIs (Free Edition, no per-call charge), workspace dbc-f374519f-f1e1.
Main model `databricks-meta-llama-3-3-70b-instruct`; cheap model `databricks-meta-llama-3-1-8b-instruct`.
Runner: `scripts/run_stage23_databricks.sh` (= `scripts/run_frozen_eval.py` on each frozen plan).

Plans (frozen on krish's machine before any model output; `scripts/prepare_stream.py --min-score 0.4575`, seeds 11/23/37):
permission `e554777a2515cf3c`, gate `cae781c3405c25c9`, stress `23433229142ecacf`.
They differ from the plan IDs in docs/STAGE_TWO_THREE.md only through the input-file hashes; same stream (4,231 tickets), same seeds.

| Run | Model | Prompt | Complete tasks | Config |
|---|---|---|---|---|
| permission-v2 | 70B | v2 | 90/90 | `daae2894016b` |
| permission-v2-cheap | 8B | v2 | 80/90 | `7594a65456c5` |
| gate-v1 / gate-v2 | 70B | v1 / v2 | 60/60 each | `c0fa29057ae1` / `daae2894016b` |
| stress-v1 / stress-bad | 70B | v1 / bad | 30/30 each | `c0fa29057ae1` / `4850304e0953` |

**Failures (first pass kept in `first-pass/`):** the 70B's only failures were Free Edition rate limits (HTTP 429),
filled by a second pass with backoff. **The 8B returned invalid JSON on 10 of 90 tasks (11%)**; those were NOT
retried, so the failure rate stays visible.

**Observed before labelling (no correctness claims yet):**
- 70B proposes a link on 89/90 permission tickets; 60 of them are "related" (over-linking). Only 2 actions reach the 0.95 AUTO cutoff.
- 8B calls "duplicate" on 48/80 and claims >= 0.95 confidence on 30 actions.
- Prompt v2 changes the 70B's action on 14/60 gate tickets; the action mix barely moves.
- The poisoned correction changes the action on 23/30 stress tickets: "duplicate" goes from 4 to 25.

**Labels needed (blind, via `app/label_app.py`):** only actions that can change a verdict.
- `permission-labels.jsonl` 3 (1 settled by a maintainer link) and `permission-cheap-labels.jsonl` 30 (1 settled): actions at >= 0.95.
- `gate-labels.jsonl` 28 and `stress-labels.jsonl` 46: both actions of every ticket where the two prompts disagree.
  Tickets where they agree are ties for the sign test and need no label.
