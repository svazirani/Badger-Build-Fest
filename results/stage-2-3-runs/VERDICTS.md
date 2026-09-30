# Assay verdicts on the Databricks runs (Sat Sep 26, ~19:30)

Agent: Apache Jira triage on Databricks Foundation Model APIs (Free Edition). Main model Llama 3.3 70B, cheap model
Llama 3.1 8B. Frozen, outcome-blind plans on the honest stream (top retrieval score >= 0.4575, 4,231 tickets).
Details of the runs: `README.md` in this folder.

## How the answers were labelled
- Only labels that can change a verdict were collected: actions at the 0.95 AUTO cutoff (permission), and tickets
  where the two prompts acted differently (learning gate). 105 labels in total.
- Maintainer links settled 2. `gpt-oss-120b` on Databricks labelled the rest blind (never seeing the proposing
  model, prompt or confidence). Claude (Opus 5.5) re-judged the 10 items where gpt-oss was unsure or under 0.8
  confident. Files: `*-labels.ai.jsonl`, `claude-adjudications.json`.
- **Human spot check** (20 random AI-labelled items, seed 7, one reviewer, blind to the AI answers):
  - Round 1, without definitions on screen: 11/20 agree (55%).
  - Round 2, with written definitions: 11/20 agree (55%, 90% interval 35–74%).
  - **By relation in round 2: duplicate 8/9 (89%, 90% interval 57–99%); related 2/7; part_of 0/2; none 1/2.**
  - Labels for "duplicate" are usable. "related" and "part_of" labels are not: even careful labellers disagree.
- Maintainer practice used for the definitions: of 6,743 pairs of tickets bumping the same dependency, 36 are
  linked, and all 22 duplicate links have the same target version. A bump to a different version is not a duplicate.

## Verdicts
| # | Question | Verdict | Evidence | Robust to label error? |
|---|---|---|---|---|
| 1 | May **Llama 8B** auto-link duplicates when it says >= 0.95? | **QUIET: no** | 4 of 19 right (21%); lower bound 5% vs target 90% | Yes: with duplicate labels ~89% reliable, it stays far below 90% |
| 1 | May **Llama 70B** act alone? | **SUGGEST** | only 2 actions reach 0.95 (1 right); part_of needs ~38 more labelled examples | n/a (too little evidence, stated as such) |
| 3 | Keep **prompt v2** (the sibling/related correction)? | **UNPROVEN** | fixes 3, breaks 3; same action on 46 of 60 tickets | Labels are mostly related/part_of (unreliable); UNPROVEN either way |
| 3 | Keep the **poisoned correction** ("version bumps are duplicates")? | **DISCARD** | fixes 0, breaks 16 (all duplicate calls), exact sign test p = 1.5e-5 | Yes: even 2 wrong labels flipped to fixes leaves 14 vs 2, p ~ 0.002 < 0.025 |
| - | 8B part_of at >= 0.95 | QUIET per labels (3/8), **not reliable** | part_of labels disagree | No: reported, not claimed |

## What we can say in the demo
- "The cheap model said it was 95%+ sure on 19 duplicate links. The evidence says about 1 in 5 was right. Assay
  refuses to let it act alone."
- "A plausible-sounding reviewer correction broke 16 decisions and fixed none. Assay rejected it."
- "Our own labels were audited too: humans and the AI labeller agree on duplicates (8/9) but not on 'related'
  (2/7), so we make no claims that rest on 'related'."

## Not claimed
- No AUTO permission was earned by any model.
- Question 2 (cost) is not certified: Free Edition hides the gateway usage tables, and the 8B failed to return valid
  JSON on 10 of 90 tasks (11%), which a fair comparison has to count as failures.
