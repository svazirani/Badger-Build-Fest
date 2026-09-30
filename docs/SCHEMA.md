# Data contract (all workstreams read/write these; JSON Lines, one object per line)

`data/tickets.jsonl`: one real Apache Jira ticket
  {key, project, created (ISO-8601), updated, summary, description (<=4000 chars), issuetype, status,
   resolution (str|null), components [str], labels [str], parent (key|null), subtasks [key],
   links [{type, direction: "outward"|"inward", key}]}

`data/truth.jsonl`: ground-truth relation between two tickets, made by real maintainers
  {src, dst, relation: "duplicate"|"part_of"|"related", evidence: "link:<type>"|"subtask"|"resolution:Duplicate"}
  (src is the NEWER ticket; dst is the earlier one it relates to)

`data/candidates.jsonl`: retrieval shortlist for a ticket (only tickets created BEFORE it)
  {key, candidates: [{key, score}]}

`data/judgments.jsonl`: a model's decision about one (ticket, candidate) pair
  {key, candidate, model, relation: "duplicate"|"part_of"|"related"|"none", confidence (0..1),
   reason, truth (relation|"none"|null), correct (bool|null), cost_usd (float|null), ts}

`data/feedback.jsonl`: a human's accept/reject in the review app
  {key, candidate, relation, decision: "accept"|"reject"|"change", new_relation (str|null), user, ts}

Time rule: learn/tune only on tickets created before 2025-01-01; evaluate on tickets created 2025-01-01 or later.

Stage 2/3 additions:

- A frozen plan contains complete ordered ticket/candidate inputs, source hashes, a `plan_id`, selection rule and limitations. The honest-stream plan contains no truth labels.
- New judgment rows include `config_id`, `plan_id`, `run_id`, `task_status`, `prompt`, `backend`, `usage`, `task_cost_usd` and `cost_basis`. Task cost and usage repeat on pair rows and must be counted once per `run_id`.
- An adjudication label is `{action_id, key, candidate|null, relation, config_id, correct: bool|null, reviewer, reason, label_status}`. `null` means unknown and is excluded, never converted to a negative label.
- A permission receipt binds the action policy, fixed threshold, configuration, family-wise error allocation, evidence action IDs, source hashes and validity interval.
- A learning-gate receipt compares paired task outcomes using independently adjudicated actions and records fixed, broken, unchanged and unknown counts.
