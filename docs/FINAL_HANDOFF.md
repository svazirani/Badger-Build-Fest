# Assay: final handoff for the deck, the demo and the Devpost

**Badger BuildFest 2026 · Applied AI & Automation · Challenges: Databricks Real-World Workflows (Xorbix), The Art of the Break**
Status as of **Sun Sep 27, 2026, early morning CDT** · Devpost closes **11:00 CDT**.

This file is the single source of truth for anyone (person or AI agent) building the slides, recording the video,
running the live demo or answering judges. **Every number here comes from a file in `results/` or a Unity Catalog table,
named next to it.** Do not round differently, invent, or "improve" a number. If something is not in this file, it is
not claimed.

---

## 0. Rules for whoever uses this file

1. **Numbers:** copy them exactly as written here, with the unit and the denominator ("1,793 of 2,321", not "most").
   Percentages are rounded to whole numbers unless shown otherwise.
2. **Say what we could not prove** (section 12). Judges reward honesty; the product *is* honesty about AI.
3. **Wording:** Assay is the product; Apache Jira triage is only the example agent. Say "high-confidence false
   positive", "proven", "ruled out", "needs N more". Never say "accurate" or "safe" without a number.
4. **Cost:** we paid **$0** (Databricks Free Edition). Dollar figures are **estimates at list price**, with an
   **assumed $0.07 per DBU** (the Databricks pricing page lists DBUs per token, not dollars per DBU).
5. **Demo tickets** are synthetic, marked with a gold border, and never written to Jira or used as evidence.

---

## 1. The pitch

**Name:** Assay (team backronym: *Agent Safety, Supervision, and Autonomy Yardstick*).

**Tagline:** *AI agents, verified.* / *Agents earn their freedom, with evidence.*

**One sentence:** Assay is an AI agent manager that decides, with evidence, which model an agent should use, what the
agent may do without a person, and whether a change actually helped. It runs on Databricks.

**30-second version:**
> Companies either trust AI agents blindly or check everything they do. Nobody decides with evidence. We tested 8 AI
> models on 1,362 real Apache Jira tickets, and graded every answer against what the Apache maintainers actually did.
> When models said they were 95% sure, they were wrong 1,793 times out of 2,321. So Assay never trusts confidence. It
> picks the cheapest model that is proven good enough, routes around busy models live, and lets the agent act alone
> only on kinds of cases the record has proven, like "a version upgrade is not a duplicate", right 248 of 249 times.
> Everything else goes to a person. All on Databricks.

**The problem:** AI agents keep asking for more freedom: act without asking, run on cheaper models, learn from
corrections. Teams decide on gut feel or on the model's own confidence. Confidence is not evidence.

**The answer (four questions Assay answers with evidence):**

| # | Question | How Assay decides | Where in code |
|---|---|---|---|
| 1 | **Which model answers?** | Cheapest model that is proven good enough; live switch when busy or broken | `assay_engine/router.py` (`policy_from_scorecard`, `route`) |
| 2 | **May the agent act alone?** | Only per model and relation, when checked precision's 95% lower bound ≥ 90% | `assay_engine/permissions.py`, `bands.py` |
| 3 | **Reuse past decisions?** | Only for kinds of cases whose past answers are proven (lower bound ≥ 90%), checked by leave-one-out | `assay_engine/precedent.py` |
| 4 | **Did a correction help?** | Test on fresh cases first: fixes N, breaks M, exact sign test | `assay_engine/learning.py`, `gate.py` |

**What is new versus what Databricks already gives you:** Databricks serves the models and its AI Gateway can route by
configuration and fail over when an endpoint is down. It does not know whether a model's answers are *right* for your
task. Assay adds the evidence layer on top: it grades answers against real outcomes, picks the cheapest model that is
proven, re-decides when evidence changes, and gates autonomy on proof. (On Free Edition the gateway's fallback works
only for external models and its usage tables are not readable, so the live router is ours.)

---

## 2. The example agent and its data

- **Agent task:** for each new Apache Jira ticket, look at up to 5 earlier look-alike tickets and say whether it is a
  **duplicate** ("same problem"), **part of** a larger effort, **related** ("connected"), or nothing.
- **Data:** 37,853 public tickets from **Spark, Kafka, Flink, Hive** (2023 onward); 13,687 maintainer links used as
  ground truth. 48% of tickets closed as duplicates were never linked to their original (lost knowledge the agent can
  recover). Source: `docs/ASSAY_REPORT.md` §4, tables `tickets`, `truth`.
- **Retrieval:** time-honest (only earlier tickets), TF-IDF + sibling vote. `assay_triage/retrieve.py`.
- **Prompt:** version v2 (`assay_triage/judge.py`).

---

## 3. How the big evaluation works (method, in plain words)

**Plan** (`results/heavy-eval/plan.json`, frozen and hash-checked; ids `05c9f239…`, `12acafea…`, stream extension
`62579df3…`, boosters `883a362e…`):

| Slice | Tickets | How chosen | Used for |
|---|---|---|---|
| Stream | **800** | uniform random from the honest stream (top retrieval score ≥ 0.4575), 2025+, disjoint from every earlier run | **precision** (the only slice precision is measured on) |
| Known duplicates | 93 | every ticket the maintainers closed as a duplicate of an earlier shortlisted ticket | recall only |
| Version upgrades | 80 | title pattern "upgrade/bump/update … version" | kind-of-case evidence |
| Test failures | 50 | title pattern "fail/flaky … test" | kind-of-case evidence |
| Boosters | 339 | kind of case read **only from the ticket text and its shortlist** (never from the answer): 42 same-version upgrades, 117 identical titles, 100 test-failure pairs, 80 version upgrades | deciding rare claims |
| **Total** | **1,362** | | |

Enriched slices (everything except the stream) are never mixed into precision. This avoids the "rigged sample" trap
we found and fixed earlier (Break Card).

**Models** (Databricks Foundation Model APIs, all 8 chat models on the workspace): Llama 3.3 70B, Llama 3.1 8B,
Llama 4 Maverick, gpt-oss 120B, gpt-oss 20B, Qwen3-Next 80B, Qwen3.5 122B (partial, rate-limited), Gemma 3 12B.

**Grading, against the maintainers' own record** (`scripts/heavy_grade.py`, no human or AI labels):
- **Confirmed:** the record says exactly this (a duplicate link; the parent ticket; any link or same parent for
  "related").
- **Contradicted:** the record says otherwise (e.g. "duplicate" of a ticket in another project, of its parent or a
  sibling, while it is marked a duplicate of something else, or it was resolved Fixed/Done/Implemented on its own;
  "part of" a ticket while its parent is another).
- **Unlinked:** no record either way (maintainers miss links), so it counts neither way.
- **Precision** = confirmed / (confirmed + contradicted). **Strict** precision counts unlinked as wrong.
- **Proven** = the 95% one-sided lower bound (Clopper-Pearson) is at least 90%. **Ruled out** = the upper bound is
  below 90%. Otherwise **pending**, with "N more" to prove it.
- **Circularity guard:** kinds of case defined by the parent field (siblings, candidate is parent) are excluded from
  claims and learned patterns, because the grader itself uses that field. "Related" answers can never be contradicted
  by the record (nobody records "unrelated"), so "related" claims use the strict count.

**Resumable runs, failures kept as data:** unreadable model output counts against the model (first try), and busy
(rate-limited) calls are retried.

---

## 4. Final results (source: `results/heavy-eval/report.json`, `REPORT.md`, tables `heavy_*`)

### 4.1 Headline numbers

| What | Number |
|---|---|
| Tickets evaluated | **1,362** (800 random stream + 562 targeted) |
| Models | **8** (7 complete; Qwen3.5 122B 46 answers, throttled) |
| Model calls on Databricks | **9,841** (9,388 answered) |
| Answers verified against the maintainer record | **5,125** (out of 9,064 proposed links) |
| High-confidence false positives (rated ≥95% confident, contradicted by the record) | **1,793 of 2,321 (77%)** |
| Claims decided | **35**: **3 proven, 32 ruled out**, 15 pending |
| Tokens used | **10,559,874** |
| Estimated compute cost at list price | **62.3 DBU ≈ $4.36** (assumed $0.07/DBU) · actual spend **$0** |

### 4.2 Model scorecard (stream slice for precision; all slices for counts)

| Model | Assay's role | Precision (checkable) | 95% lower bound | ≥95%-confident answers wrong | Unreadable | Cost / 1,000 tickets* | Median time |
|---|---|---|---|---|---|---|---|
| gpt-oss 120B | Backup | **71%** (236/331) | 67% | 47 of 104 | 89 of 1,362 | $0.51 | 3.9 s |
| Llama 3.3 70B | Backup | 60% (222/372) | 55% | 13 of 21 | 0 of 1,362 | $0.62 | 3.0 s |
| **gpt-oss 20B** | **Primary** | 58% (193/331) | 54% | 58 of 92 | 52 of 1,362 | **$0.26** | 4.7 s |
| Llama 4 Maverick | Excluded | 41% (186/456) | 37% | 30 of 42 | 2 of 1,362 | $0.64 | 3.2 s |
| Qwen3-Next 80B | Excluded | 31% (151/495) | 27% | 275 of 340 | 72 of 1,362 | $0.43 | 3.4 s |
| Gemma 3 12B | Excluded | 16% (82/509) | 14% | 395 of 432 | 6 of 1,362 | $0.27 | 4.8 s |
| Llama 3.1 8B | Excluded | 4% (26/591) | 3% | 179 of 188 | 95 of 1,362 | $0.21 | 1.8 s |
| Qwen3.5 122B | Excluded (too little data) | 71% (10/14) | 46% | 1 of 8 | 0 of 307 | $9.25 | 43.9 s |

\*List price in DBU per 1M tokens (databricks.com, fetched 2026-09-27) × assumed $0.07/DBU, from measured tokens.

**Paired comparison against Llama 3.3 70B on the same tickets** (exact sign test):
gpt-oss 120B better on 83, worse on 42 (**p = 0.0003, significantly better**); gpt-oss 20B better on 60, worse on 75
(p = 0.23, **no proven difference**); every excluded model significantly worse (e.g. Llama 8B worse on 419, better on 14).

### 4.3 Assay's model choice (the "adapts to the lowest safe price" feature)

- **Rule** (`router.policy_from_scorecard`): the cheapest model that is within 5 points of the reference model's
  precision, not significantly worse on the same tickets, at most 5% unreadable, with at least 100 answers, becomes
  **primary**. Backups: the rest with at least 50% precision, best first. Re-run on new evidence and the choice changes.
- **Result:** **Primary gpt-oss 20B** (replaced Llama 3.3 70B) · backups **gpt-oss 120B → Llama 3.3 70B** · 5 excluded.
- **Cost-optimized vs quality-optimized:** gpt-oss 20B costs **$0.26** per 1,000 tickets vs **$0.62** for Llama 70B
  (**57% cheaper**) with no proven precision loss. The **quality-optimized alternative is gpt-oss 120B**: **13 points
  more precise** (71% vs 58%) at **1.9× the cost**. The primary is deliberately *not* the most precise model.
- **Autonomy granted: none.** No model reaches 90% on any kind of case the record can check.
- Previous policy kept at `results/routing-policy-before-eval.json`; current at `results/routing-policy.json`.

### 4.4 Confidence vs reality (answers the model rated ≥95% confident; checkable ones)

| Model | Stated | Actually right | n |
|---|---|---|---|
| gpt-oss 120B | 96% | 55% | 104 |
| Llama 3.3 70B | 98% | 38% | 21 |
| gpt-oss 20B | 96% | 37% | 92 |
| Llama 4 Maverick | 99% | 29% | 42 |
| Qwen3-Next 80B | 95% | 19% | 340 |
| Gemma 3 12B | 95% | 9% | 432 |
| Llama 3.1 8B | 98% | 5% | 188 |

(Qwen3.5 122B: 88% of 8, too few to read anything into.) **Model confidence never decides anything in Assay.**

### 4.5 Why confident answers fail (1,793 high-confidence false positives, grouped by the record's reason)

| Cause (plain words) | Share | Count |
|---|---|---|
| Wrong parent project ("part of" a ticket, but it belongs under another parent) | 45% | 811 |
| Not actually a duplicate (the ticket was resolved on its own) | 39% | 698 |
| Sibling tasks, not duplicates | 8% | 135 |
| Wrong kind of link (maintainers linked them differently) | 4% | 67 |
| Across projects (tickets from different Apache projects) | 4% | 63 |
| Wrong original (a duplicate, but of another ticket) | 1% | 17 |

### 4.6 What Assay learned from past decisions (patterns, `assay_engine/precedent.py`)

Built from **1,697 decisions** (1,602 maintainer record, 77 audited AI labels, 18 human). Proven patterns are applied
automatically; everything else goes to a person.

| Pattern (kind of case → answer) | Evidence | Lower bound | Status |
|---|---|---|---|
| Version upgrade of the same library to a different version is **not the same problem** | **248 of 249** | 98% | **Proven, automated** |
| Version upgrades are **not part of** each other | **219 of 219** | 99% | **Proven, automated** |
| Two tickets with identical titles are **not part of** each other | **44 of 44** | 93% | **Proven, automated** |
| Version upgrades are **related** | 57 of 61 | 86% | Pending: 28 more agreeing decisions (see 4.9) |
| Identical titles are **not the same problem** | 132 of 152 | 82% | Pending (answers mixed) |

**Leave-one-out check** (hide each past decision, predict it from the rest): the patterns would have answered
**512 of 1,697** decisions automatically, **511 correctly** (lower bound **99.1%**).

**Findings from the claims table** (`coverage` in the report):
- Links **across Apache projects** were right **0 of 137** times → Assay interrupts them.
- **Identical titles** labeled "same problem" were right only **115 of 609** times (19%).
- Every "may act alone" claim for every model is **ruled out** or pending.

**Important nuance for Q&A:** the routed models (gpt-oss 20B/120B, Llama 70B) almost never make the mistakes these
patterns catch; on version upgrades gpt-oss 20B said "related" 155 of 156 times. The patterns protect against the
**cheaper models' known mistakes** (Llama 3.1 8B labeled version upgrades "same problem" or "part of" 174 of 186
times). That is exactly the demo: *Assay makes a cheap model safe*.

### 4.7 Live model routing (`results/heavy-eval/routed-*.jsonl`, table `routing_log`)

| Test | Requests | Answered without a person | Live switches | Held for review | Escalated to a person | Median time |
|---|---|---|---|---|---|---|
| **Normal load** (all 800 stream tickets, evidence-based policy) | 800 | **750 (94%)** | **568** after 1,036 rate-limit responses | 618 | 50 | 5.4 s |
| Stress (44 concurrent calls, old backup order) | 300 | 163 (54%) | 78 | 215 | 137 | 4.6 s |

Who answered in the normal test: gpt-oss 20B 182 · gpt-oss 120B 234 · Llama 70B 334 · nobody 50. Free Edition rate
limits are low, so the primary was often busy and the backups carried the load; backup answers are held for review.
Precision of routed answers (checkable): primary 44 of 71 (62%), backups 156 of 246 (63%).
`routing_log` holds **1,216** logged requests in total (all runs and live demos).

### 4.8 Definition ambiguity (93 tickets the maintainers closed as duplicates)

How often each model named the maintainers' duplicate: Llama 4 Maverick 73/92 · gpt-oss 20B 63/93 · Qwen3-Next 80B
61/89 · Llama 70B 59/93 · Llama 8B 54/93 · Gemma 51/93 · gpt-oss 120B 50/91. The rest were called "part of",
"related", another ticket, or nothing: even "duplicate" is ambiguous, so these stay with a person.

### 4.9 AI-assisted review of "related" version-upgrade suggestions (**pending one command**)

- Every open, non-demo suggestion of this kind was reviewed (**152**, none cherry-picked; 15 demo tickets excluded).
  Verdicts proposed by Claude with a reason each, **approved by krish**: **147 accept** (same project, same
  dependency), **5 reject** (different Apache projects). File: `results/assisted-review/2026-09-27-related-version-upgrades.json`.
- Once recorded, the pattern becomes **204 of 213, lower bound 92.7%: proven**, and the dashboard auto-resolves these.
- **Status: NOT yet written to Databricks.** Run once:
  `python scripts/record_assisted_review.py results/assisted-review/2026-09-27-related-version-upgrades.json --write`
- Safeguard (deployed): **cross-project links are never accepted automatically**, even under a proven pattern.
- Disclose it as "AI-assisted review approved by a person"; it is labeled that way in the audit trail.

### 4.10 Earlier results that still stand (Stage 2/3, `results/stage-2-3-runs/VERDICTS.md`)

- Cheap model (Llama 3.1 8B) said "95% sure" on 19 duplicates: **4 were right** → not allowed to act.
- A plausible rule ("version upgrades are duplicates") tested on 30 fresh tickets: **fixed 0, broke 16**
  (p = 1.5×10⁻⁵) → blocked before use.
- New instructions (prompt v2): **fixed 3, broke 3** → no proof they are better, old ones kept.

### 4.11 Replay events (how the verdicts formed, in ticket-arrival order; `replay` in the report)

100 tickets: *Automated: "same problem" on version upgrades* · 150: *Primary changes to gpt-oss 20B*, gpt-oss 120B and
Llama 70B become backups, Maverick excluded · 250: *Automated: "part of" on version upgrades* · 300–700: Llama 70B
moves between backup and excluded as its precision hovers around the 50% backup bar · 900: *Automated: "part of" on
identical titles*. (An earlier partial run also showed a pattern being **revoked after a counterexample** and
re-proven, which the replay can show when evidence flips.)

---

## 5. The dashboard (the demo)

**URL:** https://assay-manager-7474654480147366.aws.databricksapps.com (Databricks login; the Databricks App
`assay-manager`, FastAPI + one page, code in `app/manager/`). **Free Edition apps stop 24 h after a deploy:** run
`python scripts/deploy_manager.py` before judging and open the page once to wake the SQL warehouse (first load up to
a minute).

**Deep links:** `#tour` (guided tour) · `#tour=N` (tour at step N) · `#play` (start the replay loop at once) ·
`#replay=N` (replay paused at snapshot N).

**Sections, top to bottom:**
1. **Hero:** "AI agents, verified." + gold **Live demo** button.
2. **Key figures:** tickets evaluated, answers verified, high-confidence false positives, claims decided, each with a
   one-line description and a **?** tip (tips open after 1 s hover, tap or focus; expanded during the tour).
3. **Replay bar:** plays automatically in a loop (100 tickets → all, 5 s hold); key figures, model table and routing
   animate; event feed shows automations, revocations and role changes.
4. **Model evaluation:** ranked by precision (rows slide); bold column headers each with a **?**; roles Primary /
   Backup / Excluded with the reason on hover.
5. **Detailed statistics** (collapsible): **Assay's model choice** card (cost-optimized primary vs quality-optimized
   alternative, backups, autonomy none) · **Price vs performance** chart (moves with the replay) · Calibration ·
   Definition ambiguity · Evidence coverage.
6. **Cost & savings:** estimated cost of all tokens, 57% lower cost per ticket, projected monthly saving at 1M
   tickets ($355), share of reviews automated (30%), per-model token/DBU/cost table.
7. **Model routing:** where the 800 requests went, answered without a person (94%), switches, backup precision,
   median time; primary/backups/excluded; stress-test line.
8. **Review queue** (collapsible): suggestions the record cannot settle; cards say "Suggested by *model* · model
   confidence X%", the two tickets (Jira links), the model's reason, "Similar past cases …, N more agreeing decisions
   to automate", Accept / Reject / Skip (saved to Delta `actions`, undo 6 s). "How to read a suggestion" guide with
   numbered markers ①–⑥ during the tour. Demo tickets have a gold border.
9. **Why confident answers fail:** the cause table of 4.5 with example links.

**Tour (13 steps):** Assay → key figures → replay → model evaluation → detailed statistics → cost → routing → review
queue → how to read a suggestion → try it (answer one real card) → why confident answers fail → live demo → help.

---

## 6. The live demo screen (gold "Live demo" button)

Write a Jira ticket (or pick a template); Assay runs it live on Databricks and shows 4 steps: ① earlier look-alikes
found (keyword search in the `tickets` table) → ② which model answered (and any switch) → ③ the model's suggestion
and confidence → ④ **Assay's decision**, one of:
- 🟢 **Handled automatically** (a proven pattern applies),
- 🔴 **Interrupted: known to be wrong** (e.g. cross-project links, right 0 of 137),
- 🟡 **Sent to you** (anything unproven; lands in the Review queue with a gold "Demo" border),
- or "No link proposed".

**Templates (measured, not assumed):**

| Template | Model | Result in testing |
|---|---|---|
| **Cheapest model on a version upgrade** ("Upgrade Netty to 4.2.8.Final") | forced Llama 3.1 8B | **Handled automatically 10 of 10**: 8B says "same problem as *Upgrade Netty to 4.2.18.Final*", Assay rejects it from the 248/249 pattern |
| **Copy from another project** (KAFKA "Support TimeType in RowToColumnConverter") | router | **Interrupted** (1 of 1): model said "duplicate, 95%" of the SPARK ticket; Assay: "links across projects were right 0 of 137 times" |
| **Genuinely new request** (Spark Connect retry with backoff) | router | **Sent to you** (1 of 1) |
| Blank | any | write your own |

Model choices: router (default), force Llama 3.1 8B, force Gemma 3 12B, force gpt-oss 120B. Live outputs vary
because models sample; run each template once before presenting. The small button "Or process 3 real new Jira
tickets" runs three unseen real tickets through the router (proof the loop is live; does not change the evaluation).

**What to say at step ④ of the Netty template:**
> "Even if you switch to the cheapest model, Assay catches its known mistakes automatically: no person needed. That's
> how Assay makes cheap models safe."

**If gpt-oss 120B answers "related" correctly and it still goes to review:** that is by design. The "related on
version upgrades" pattern is 57 of 61 (lower bound 86%, below the 90% bar); 28 more agreeing decisions prove it
(section 4.9). Line: *"Even a correct, 96%-confident answer waits until the evidence proves the pattern."*

---

## 7. Demo scripts

For the final seven-slide presentation, use the timing in `SUBMISSION_KIT.md` section 2 and the speaker notes in
`docs/Assay_Presentation_v7.pptx`. The scripts below are alternative dashboard-led formats, not the final deck's timing.

### 7.1 Two-minute video

| Time | Screen | Voice |
|---|---|---|
| 0:00–0:12 | Title | "AI agents want freedom: to act alone, to run cheaper, to learn from corrections. Most teams decide on gut feel. Assay decides with evidence." |
| 0:12–0:30 | Dashboard top, replay playing | "We tested 8 models on 1,362 real Apache Jira tickets and graded every answer against what the maintainers actually did. When models said they were 95% sure, they were wrong 1,793 times out of 2,321." |
| 0:30–0:50 | Model evaluation + model-choice card | "Assay picks the cheapest model that is proven good enough: gpt-oss 20B, 57% cheaper than Llama 70B with no proven loss. The more precise gpt-oss 120B costs twice as much, so it's a backup." |
| 0:50–1:15 | Live demo, Netty template | "Watch the cheapest model on a version upgrade. It's 90% sure this is a duplicate. It's wrong, and Assay knows: reviewers rejected this kind of case 248 of 249 times. Handled automatically, no person needed." |
| 1:15–1:30 | Live demo, cross-project template | "A copy from another project: the model is 95% sure. Assay interrupts: cross-project links were right 0 of 137 times." |
| 1:30–1:45 | Model routing | "When the primary is rate-limited, Assay switches live: 568 switches over 800 requests, 94% answered without a person." |
| 1:45–2:00 | Review queue / close | "Everything unproven comes to a person. No model has earned full autonomy yet, and Assay tells you exactly what it would take. Agents earn their freedom." |

### 7.2 Three-minute live pitch (finalists)

1. Problem (20 s) → the 1,793 of 2,321 number (15 s).
2. Replay playing (20 s): "watch the verdicts form as tickets arrive".
3. Model choice + price vs performance (30 s).
4. Live demo, three templates (60 s): handled / interrupted / sent to you.
5. Routing (15 s), Break Card (20 s), close (10 s).
Fallback if the live call is slow: `#replay=…` screenshots, the Review queue's "resolved automatically" count, the
Proven rows in Evidence coverage.

---

## 8. Final seven-slide deck (updated September 27, 2026)

The current presentation is **`docs/Assay_Presentation_v7.pptx`**, in the repository. v7 is v6 with the Assay
logo on the title slide; nothing else changed. Versions v3–v6 are kept locally, outside the repository, and v7
supersedes them for this pitch. The earlier Slides artifact and the first deck (kept on the `old` branch) are not the final deck.

1. **Assay:** the manager for your AI agents; agents earn their freedom with evidence.
2. **Market and risk:** incorporates slide 3 from the user's Downloads copy of `Assay_Presentation_v3.pptx`.
3. **The manager's decision:** approve, reject, or let the agent act; 1,793 of 2,321 checkable high-confidence answers
   were wrong, followed by Assay's four functions.
4. **Assay in action:** the review-queue screenshot and the four-step workflow. Jira is the example, not the product's limit.
5. **Model cost and precision:** annotated screenshot, with dotted guides and shaded comparison regions.
6. **Measured cost and evidence-based control:** cost screenshot and the Databricks components; estimated cost is
   distinguished from actual Free Edition spend of $0.
7. **Team and next steps:** implementation experience, proposed next 6–12 months, a pilot-team/Databricks-mentor ask,
   and the repository QR code.

The external figures on slide 2 are forecasts, not Assay test results or a measured Assay addressable market:

- [MarketsandMarkets AI Agents Market report](https://www.marketsandmarkets.com/Market-Reports/ai-agents-market-15761548.html):
  $7.84B estimate for 2025 and $52.62B forecast for 2030 (rounded on the slide).
- [Gartner, June 25, 2025](https://www.gartner.com/en/newsroom/press-releases/2025-06-25-gartner-predicts-over-40-percent-of-agentic-ai-projects-will-be-canceled-by-end-of-2027):
  predicts over 40% of agentic AI projects will be canceled by the end of 2027 because of cost, unclear value and risk controls.

Screenshot values are a dashboard snapshot: 59% primary precision, 58% lower cost and +12 points for the quality
alternative. Section 4's frozen evaluation reports 58%, 57% and +13 respectively. Do not silently mix the two snapshots.

The graph annotations affect the presentation image only; application code was not changed. The deck includes
manual fade transitions and speaker notes structured for 120 seconds, following the supplied winning-pitch guide.
Package integrity, geometry/font checks and re-import passed; all seven slides were rendered and visually reviewed.
Native PowerPoint playback and the actual spoken duration have not been verified. Rehearse before recording.

---

## 9. The Art of the Break (everything that broke, with numbers)

**From the evaluation (this report):**
| What broke | Number | What we changed |
|---|---|---|
| "95% sure" is not 95% right | 1,793 of 2,321 wrong | confidence never decides; proof does |
| Plausible rule was poison | fixed 0, broke 16 | every correction is tested before use |
| Cheap model output unusable | Llama 8B 95 of 1,362 unreadable | failures count against a model |
| Our own first sample was rigged | balanced + inserted answers | honest random stream; boosters never in precision |
| Identical titles look like duplicates | right 115 of 609 | never merge on title alone |
| Cross-project look-alikes | right 0 of 137 | interrupted; never auto-accepted |
| Rate limits under load | stress: 137 of 300 escalated | live switch; backups held for review |
| Per-model "related" looked perfect | 35 of 35, but unfalsifiable | the record cannot contradict "related"; use pooled evidence with real negatives |
| A pattern was proven, then a counterexample arrived | revoked, re-proven later | automation is revocable (replay) |

**From Mohit's security work** (`docs/META_ART_OF_BREAK_CARD.md`, `docs/ART_OF_BREAK_BREAK_CARD.md`,
`results/security-tests/SECURITY_TEST_RESULTS.md`):
- **Prompt injection on the real Llama 3.3 70B endpoint:** 2 of 3 attacks succeeded (a fake `<system>` message in the
  new ticket, and instructions hidden in the earlier ticket) and returned "duplicate, 100%" for two unrelated tickets.
  Each payload tried once: evidence the failure exists, not a rate. Assay's gate still keeps such output as a
  suggestion, not an action.
- **Local security tests:** 23 tests, 17 pass, **6 documented open breaks** (marked strict expected failures):
  forgeable receipt hash (not signed), review of an unknown suggestion accepted, anonymous direct writes to
  `/api/answer` and `/api/undo` (bypassing the Databricks login proxy), confidence 1.01 / infinity accepted as AUTO.
- **Statistical breaks** (`docs/ART_OF_BREAK_BREAK_CARD.md`): correlated evidence (one job counted as 50), cherry-
  picked easy wins, certifying a cheaper option too soon: reproduced; the third was fixed in code.

---

## 10. Built on Databricks (Free Edition)

**Unity Catalog `workspace.assay_triage`:**
| Table | What it holds |
|---|---|
| `tickets` (37,853), `truth` (13,687), `candidates`, `stream` (4,051) | inputs |
| `heavy_scorecard`, `heavy_summary`, `heavy_cases` | the 1,362-ticket evaluation (scorecard, calibration, coverage, patterns, replay, causes, every graded answer) |
| `proposals` (826), `past_decisions` (1,697), `verdicts` | dashboard inputs |
| `actions` | every Accept/Reject (dashboard clicks, assisted review) |
| `routing_log` (1,216) | every routed request, models tried, why |
| `live_proposals` | suggestions from live runs and the demo |
| `precedents` | earlier pattern memory |

Volume `/Volumes/workspace/assay_triage/data` holds the raw JSONL (`scripts/fetch_data.py` downloads it).
**Models:** 8 Foundation Model API endpoints (app service principal has CAN_QUERY on all). **Apps:** `assay-manager`
(the demo) and `assay` (technical workbench). **SQL warehouse:** Serverless Starter.

---

## 11. Reproduce everything

```bash
python scripts/fetch_data.py                                   # data from the volume
python -m pytest -q tests                                      # 88 passed, 6 xfailed (documented breaks)
python scripts/heavy_eval.py plan|extend|extend-stream|boost   # frozen plans (no model calls)
ASSAY_ALLOW_MODEL_CALLS=1 python scripts/heavy_eval.py run --workers 3     # all models ($0 on Free Edition)
ASSAY_ALLOW_MODEL_CALLS=1 python scripts/heavy_eval.py route --workers 6 --delta --tag normal
python scripts/heavy_grade.py --replay 50 --delta              # grade + replay + publish tables (~9 min)
python scripts/live_route.py --policy-from-eval                # cheapest proven model -> routing-policy.json
python scripts/sync_results.py                                 # dashboard tables
python scripts/deploy_manager.py                               # (re)deploy the dashboard
python scripts/record_assisted_review.py <review.json> --write # record an approved assisted review
```

---

## 12. What we do not claim (say these out loud)

- **No model has earned the right to act alone** on any kind of case the record can check.
- The primary (gpt-oss 20B) is **58%** precise on checkable answers; the agent **suggests**, people decide, except
  for the 3 proven patterns.
- Precision uses only answers the record can settle; maintainers miss links (48% of duplicate closures unlinked), so
  true precision may be higher, and "related" cannot be contradicted at all.
- Dollar figures are list-price **estimates** with an assumed $0.07/DBU; we paid $0.
- Qwen3.5 122B was only partly tested (46 answers) because of Free Edition rate limits.
- Routing results are on Free Edition's low rate limits; switch counts would differ on a paid workspace.
- The assisted review (4.9) is AI-proposed and human-approved, not an independent human review.
- Six security weaknesses are documented and still open (section 9).
- Four Apache projects and one task only.

## 13. What's next

An API any agent can call (proposal in → act / ask / hold out) · scheduled agent runs as a Databricks job · signed
receipts and identity-checked writes (closing the security breaks) · risk-tiered bars (e.g. lower for "see also"
links, decided up front) · more human reviews so more patterns can be proven · more agents than Jira triage.

---

## 14. Likely judge questions

- **Why isn't the primary the most precise model?** The rule optimizes cost with a quality floor: gpt-oss 20B is
  57% cheaper than Llama 70B with no proven loss. gpt-oss 120B is 13 points more precise at 1.9× the cost; under a
  quality-first policy it would be primary.
- **1,362 tickets and you still need more data?** Evidence is per kind of case, and only checkable answers count.
  "Related" on version upgrades had 616 answers but only 81 the record could confirm; with 4 disagreements, 28 more
  agreeing decisions prove it.
- **Why not trust a good model's own track record?** Assay does (permissions are per model), but for "related" the
  record can only confirm, never contradict, so a per-model 100% is unfalsifiable. Pooled evidence includes real
  negatives from human and AI reviews.
- **Didn't you pick easy tickets?** Precision uses only the 800 random stream tickets. Booster slices are chosen by
  kind of case from ticket text only, never from the answer, and never counted in precision.
- **Isn't the grading circular?** Where it would be (parent-field kinds), we excluded those claims.
- **Is it expensive?** $0 on Free Edition; the whole 9,841-call evaluation is about $4.36 at list price.
- **What stops prompt injection?** Nothing in the model; that's why its output is only a suggestion until evidence
  allows more (and two of three attacks succeeded against the model itself).
- **What does Databricks give you vs what you built?** Databricks: models, tables, the app, identity. Assay: grading
  against outcomes, cheapest-proven routing, live switching, proven-pattern automation, the dashboard.

## 15. Glossary

- **Primary / backup / excluded:** the model that answers first / answers when the primary is unavailable (held for
  review) / never used.
- **Precision:** of answers the maintainer record can settle, the share it confirms.
- **High-confidence false positive:** an answer the model rated ≥95% confident that the record contradicts.
- **Proven / ruled out / pending:** 95% interval entirely above / below the 90% bar / neither (with "N more").
- **Pattern (precedent):** a kind of case whose past decisions agree enough to be proven; applied automatically.
- **Leave-one-out:** hide each past decision and check whether the patterns would have predicted it.
- **DBU:** Databricks Unit, the billing unit; the pricing page lists DBUs per million tokens.
- **Free Edition:** the free Databricks tier we ran on (low rate limits, apps stop after 24 h).

## 16. Checklist before 11:00

- [ ] Run the assisted-review `--write` (section 4.9) if the team wants the "related" pattern proven.
- [ ] Redeploy the dashboard (`python scripts/deploy_manager.py`) and open it once; test the three demo templates.
- [x] Prepare the final seven-slide deck: `docs/Assay_Presentation_v7.pptx` (section 8).
- [ ] Rehearse the two-minute notes and check the deck's fades in PowerPoint before recording.
- [ ] Record the video (section 7.1); keep a clip of the Netty demo as a fallback.
- [ ] Devpost: paste from `docs/SUBMISSION_KIT.md` with numbers updated from this file; declare Xorbix + Art of the Break.
- [ ] Commit and push the latest changes; rotate the API key that was pasted in chat earlier.
