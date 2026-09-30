# Heavy evaluation on Databricks (8 models)

Plan `05c9f2397fd3`: 800 stream tickets (precision) + 93 maintainer-confirmed duplicates (recall, reported separately). Prompt v2. Graded only against the Apache maintainers' own record. Strict = unlinked counted wrong; decided = only cases the record settles.

| Model | Answered | Unusable | Actions | Strict precision [95% lower] | Decided | ≥0.95 conf: strict | Confident & contradicted | Dup recall | p50 s | Tokens/task | $/1k tasks* |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Qwen3.5 122B | 46/307 | 0 | 24 | 42% [25%] | 71% | 64% (n=11) | 1 | 10/12 | 43.9 | 4916 | 9.251 |
| gpt-oss 120B | 1294/1362 | 89 | 747 | 32% [29%] | 71% | 37% (n=153) | 47 | 50/91 | 3.9 | 1426 | 0.507 |
| Llama 3.3 70B | 1362/1362 | 0 | 762 | 29% [26%] | 60% | 29% (n=28) | 13 | 59/93 | 3.0 | 899 | 0.617 |
| gpt-oss 20B | 1320/1362 | 52 | 687 | 28% [25%] | 58% | 26% (n=129) | 58 | 63/93 | 4.7 | 1473 | 0.262 |
| Llama 4 Maverick | 1360/1362 | 2 | 792 | 23% [21%] | 41% | 23% (n=53) | 30 | 73/92 | 3.2 | 898 | 0.644 |
| Qwen3-Next 80B | 1324/1362 | 72 | 759 | 20% [18%] | 31% | 16% (n=408) | 275 | 61/89 | 3.4 | 1017 | 0.433 |
| Gemma 3 12B | 1359/1362 | 6 | 772 | 11% [9%] | 16% | 7% (n=536) | 395 | 51/93 | 4.8 | 1106 | 0.271 |
| Llama 3.1 8B | 1323/1362 | 95 | 761 | 3% [2%] | 4% | 4% (n=223) | 179 | 54/93 | 1.8 | 944 | 0.211 |

## Assay's verdict per model

| Model | Role (cheapest proven wins) | Why | Acts alone? | vs Llama 3.3 70B (same tickets) |
|---|---|---|---|---|
| gpt-oss 120B | backup | 7% unreadable answers (limit 5%). Used only when the main model is busy; its answers wait for review | no (89 of 1362 answers unreadable; said 95%+ sure and was contradicted 47 of 153 times) | better on 83, worse on 42 (p=0.00031) |
| Llama 3.3 70B | backup | meets every rule; used when the main model is busy, its answers wait for review | no (said 95%+ sure and was contradicted 13 of 28 times) | – |
| gpt-oss 20B | main | cheapest model that meets every rule | no (said 95%+ sure and was contradicted 58 of 129 times) | better on 60, worse on 75 (p=0.228) |
| Qwen3.5 122B | not used | only 46 answers so far (needs 100) | no (right on only 10 of 14 answers the record can check) | better on 4, worse on 0 (p=0.125) |
| Llama 4 Maverick | not used | 41% right vs 60% for Llama 70B; worse on the same tickets (140 vs 21) | no (right on only 186 of 456 answers the record can check; said 95%+ sure and was contradicted 30 of 53 times) | better on 21, worse on 140 (p=8.86e-23) |
| Qwen3-Next 80B | not used | 5% unreadable answers (limit 5%); 31% right vs 60% for Llama 70B; worse on the same tickets (212 vs 15) | no (right on only 151 of 495 answers the record can check; 72 of 1362 answers unreadable; said 95%+ sure and was contradicted 275 of 408 times) | better on 15, worse on 212 (p=1.04e-45) |
| Gemma 3 12B | not used | 16% right vs 60% for Llama 70B; worse on the same tickets (281 vs 7) | no (right on only 82 of 509 answers the record can check; said 95%+ sure and was contradicted 395 of 536 times) | better on 7, worse on 281 (p=1.25e-73) |
| Llama 3.1 8B | not used | 7% unreadable answers (limit 5%); 4% right vs 60% for Llama 70B; worse on the same tickets (419 vs 14) | no (right on only 26 of 591 answers the record can check; 95 of 1362 answers unreadable; said 95%+ sure and was contradicted 179 of 223 times) | better on 14, worse on 419 (p=7.05e-105) |

## Coverage: does every claim reach a verdict?

| Claim | Evidence | 95% interval | Status |
|---|---|---|---|
| Gemma 3 12B may act alone on "same problem" (when 95%+ sure) | 0/90 | 0–4% | disproven |
| Gemma 3 12B may act alone on "part of a bigger project" (when 95%+ sure) | 24/411 | 4–9% | disproven |
| Gemma 3 12B may act alone on "connected" (when 95%+ sure) | 13/35 | 20–56% | disproven |
| gpt-oss 120B may act alone on "same problem" (when 95%+ sure) | 0/30 | 0–13% | disproven |
| gpt-oss 120B may act alone on "part of a bigger project" (when 95%+ sure) | 22/55 | 26–55% | disproven |
| gpt-oss 120B may act alone on "connected" (when 95%+ sure) | 35/68 | 38–65% | disproven |
| gpt-oss 20B may act alone on "same problem" (when 95%+ sure) | 0/42 | 0–9% | disproven |
| gpt-oss 20B may act alone on "part of a bigger project" (when 95%+ sure) | 19/54 | 22–50% | disproven |
| gpt-oss 20B may act alone on "connected" (when 95%+ sure) | 15/33 | 27–65% | disproven |
| Llama 3.1 8B may act alone on "same problem" (when 95%+ sure) | 1/144 | 0–4% | disproven |
| Llama 3.1 8B may act alone on "part of a bigger project" (when 95%+ sure) | 5/71 | 2–16% | disproven |
| Llama 3.1 8B may act alone on "connected" (when 95%+ sure) | 3/8 | 7–78% | disproven |
| Llama 3.3 70B may act alone on "same problem" (when 95%+ sure) | 0/13 | 0–27% | disproven |
| Llama 3.3 70B may act alone on "part of a bigger project" (when 95%+ sure) | 8/14 | 27–84% | disproven |
| Llama 3.3 70B may act alone on "connected" (when 95%+ sure) | 0/1 | 0–98% | undecided |
| Llama 4 Maverick may act alone on "same problem" (when 95%+ sure) | 0/12 | 0–29% | disproven |
| Llama 4 Maverick may act alone on "part of a bigger project" (when 95%+ sure) | 12/41 | 15–47% | disproven |
| Llama 4 Maverick may act alone on "connected" (when 95%+ sure) | 0/0 | 0–100% | undecided |
| Qwen3-Next 80B may act alone on "same problem" (when 95%+ sure) | 1/168 | 0–4% | disproven |
| Qwen3-Next 80B may act alone on "part of a bigger project" (when 95%+ sure) | 28/196 | 9–20% | disproven |
| Qwen3-Next 80B may act alone on "connected" (when 95%+ sure) | 36/44 | 66–92% | undecided |
| Qwen3.5 122B may act alone on "same problem" (when 95%+ sure) | 0/1 | 0–98% | undecided |
| Qwen3.5 122B may act alone on "part of a bigger project" (when 95%+ sure) | 2/3 | 8–99% | undecided |
| Qwen3.5 122B may act alone on "connected" (when 95%+ sure) | 5/7 | 26–97% | undecided |
| Past answers can be reused: "connected" for a version upgrade vs an earlier upgrade of the same library to a different version (answer: Yes) | 57/61 | 86–98% | undecided |
| Past answers can be reused: "same problem" for two tickets with the same title (answer: No) | 132/152 | 82–91% | undecided |
| Past answers can be reused: "connected" for two failing or flaky test reports (answer: Yes) | 7/7 | 65–100% | undecided (≈22 more) |
| Past answers can be reused: "same problem" for two failing or flaky test reports (answer: No) | 57/62 | 84–97% | undecided |
| Past answers can be reused: "same problem" for a version upgrade vs an earlier upgrade of the same library to a different version (answer: No) | 248/249 | 98–100% | proven |
| Past answers can be reused: "same problem" for two upgrades of the same library to the same version (answer: No) | 50/60 | 73–91% | undecided |
| Past answers can be reused: "part of a bigger project" for a version upgrade vs an earlier upgrade of the same library to a different version (answer: No) | 219/219 | 99–100% | proven |
| Past answers can be reused: "part of a bigger project" for two tickets with the same title (answer: No) | 44/44 | 93–100% | proven |
| Past answers can be reused: "part of a bigger project" for two failing or flaky test reports (answer: No) | 7/7 | 65–100% | undecided (≈22 more) |
| Past answers can be reused: "part of a bigger project" for two upgrades of the same library to the same version (answer: No) | 27/27 | 90–100% | undecided (≈2 more) |
| Past answers can be reused: "connected" for two upgrades of the same library to the same version (answer: Yes) | 6/6 | 61–100% | undecided (≈23 more) |
| Past answers can be reused: "connected" for two tickets with the same title (answer: Yes) | 3/3 | 37–100% | undecided (≈26 more) |
| "part of a bigger project" suggestions are right (all models, all kinds of case) | 219/1696 | 12–14% | disproven |
| "connected" suggestions are right (all models, all kinds of case, unlinked counted as not shown) | 1058/4018 | 25–28% | disproven |
| "same problem" suggestions are right (all models, all kinds of case) | 425/2371 | 17–19% | disproven |
| "connected" suggestions are right, for tickets with no special pattern | 64/1877 | 3–4% | disproven |
| "same problem" suggestions are right, for tickets with no special pattern | 230/824 | 25–31% | disproven |
| "same problem" suggestions are right, for two tickets with the same title | 115/609 | 16–22% | disproven |
| "connected" suggestions are right, for a version upgrade vs an earlier upgrade of the same library to a different version | 81/616 | 11–16% | disproven |
| "connected" suggestions are right, for two failing or flaky test reports | 12/470 | 2–4% | disproven |
| "same problem" suggestions are right, for a version upgrade vs an earlier upgrade of the same library to a different version | 3/351 | 0–2% | disproven |
| "same problem" suggestions are right, for two failing or flaky test reports | 20/155 | 9–18% | disproven |
| "same problem" suggestions are right, for two upgrades of the same library to the same version | 54/208 | 21–31% | disproven |
| "connected" suggestions are right, for two upgrades of the same library to the same version | 13/92 | 9–22% | disproven |
| "connected" suggestions are right, for two tickets with the same title | 7/82 | 4–15% | disproven |
| "any link" suggestions are right, for tickets in different Apache projects | 0/137 | 0–2% | disproven |

## Past-decision patterns (1697 decisions: {'ai': 77, 'human': 18, 'maintainer': 1602})

| Relation | Kind of case | Answer | Agree | Lower | Handled automatically? |
|---|---|---|---|---|---|
| duplicate | no recognised pattern | reject | 342/395 | 0.83 | no |
| part_of | no recognised pattern | reject | 326/333 | 0.96 | no |
| duplicate | a version upgrade vs an earlier upgrade of the same library to a different version | reject | 248/249 | 0.98 | yes |
| part_of | a version upgrade vs an earlier upgrade of the same library to a different version | reject | 219/219 | 0.99 | yes |
| duplicate | two tickets with the same title | reject | 132/152 | 0.81 | no |
| duplicate | two failing or flaky test reports | reject | 57/62 | 0.84 | no (≈615 more) |
| related | a version upgrade vs an earlier upgrade of the same library to a different version | accept | 57/61 | 0.86 | no (≈159 more) |
| duplicate | two upgrades of the same library to the same version | reject | 50/60 | 0.73 | no |
| related | no recognised pattern | accept | 45/49 | 0.82 | no |
| part_of | two tickets with the same title | reject | 44/44 | 0.93 | yes |
| part_of | two upgrades of the same library to the same version | reject | 27/27 | 0.90 | no (≈2 more) |
| related | two sub-tasks of the same parent | accept | 8/9 | 0.57 | no |
| part_of | two sub-tasks of the same parent | reject | 5/7 | 0.34 | no |
| related | two failing or flaky test reports | accept | 7/7 | 0.65 | no (≈22 more) |
| part_of | two failing or flaky test reports | reject | 7/7 | 0.65 | no (≈22 more) |
| related | two upgrades of the same library to the same version | accept | 6/6 | 0.61 | no (≈23 more) |
| duplicate | two sub-tasks of the same parent | reject | 4/5 | 0.34 | no |
| related | two tickets with the same title | accept | 3/3 | 0.37 | no (≈26 more) |
| part_of | the earlier ticket is already the new ticket's parent | accept | 2/2 | 0.22 | no (≈27 more) |

Leave-one-out: auto-resolved 512 of 1697, right 511 (lower bound 0.99)

*List price: DBU per 1M tokens from databricks.com (fetched 2026-09-27) × an ASSUMED $0.07/DBU. Our actual cost on Free Edition: $0.

## Live router (normal = alone; stress = alongside 32 evaluation calls)

```
{
 "normal": {
  "requests": 800,
  "switches": 568,
  "held_for_review": 618,
  "unanswered": 50,
  "answered_by": {
   "gpt-oss 20B": 182,
   "gpt-oss 120B": 234,
   "Llama 3.3 70B": 334,
   "nobody": 50
  },
  "busy_events": 1036,
  "unusable_events": 16,
  "latency_ms_p50": 5365,
  "precision": {
   "n": 703,
   "confirmed": 200,
   "contradicted": 117,
   "unlinked": 386,
   "strict": 0.2844950213371266,
   "strict_lower": 0.25650363257614256,
   "decided": 0.6309148264984227,
   "optimistic": 0.833570412517781
  },
  "precision_trusted": {
   "n": 156,
   "confirmed": 44,
   "contradicted": 27,
   "unlinked": 85,
   "strict": 0.28205128205128205,
   "strict_lower": 0.22309619219097881,
   "decided": 0.6197183098591549,
   "optimistic": 0.8269230769230769
  },
  "precision_held": {
   "n": 547,
   "confirmed": 156,
   "contradicted": 90,
   "unlinked": 301,
   "strict": 0.2851919561243144,
   "strict_lower": 0.2534421926754062,
   "decided": 0.6341463414634146,
   "optimistic": 0.8354661791590493
  }
 },
 "stress": {
  "requests": 300,
  "switches": 78,
  "held_for_review": 215,
  "unanswered": 137,
  "answered_by": {
   "Llama 3.3 70B": 85,
   "Qwen3-Next 80B": 59,
   "gpt-oss 120B": 19,
   "nobody": 137
  },
  "busy_events": 501,
  "unusable_events": 7,
  "latency_ms_p50": 4557,
  "precision": {
   "n": 157,
   "confirmed": 43,
   "contradicted": 41,
   "unlinked": 73,
   "strict": 0.27388535031847133,
   "strict_lower": 0.21575946572973306,
   "decided": 0.5119047619047619,
   "optimistic": 0.7388535031847133
  },
  "precision_trusted": {
   "n": 79,
   "confirmed": 20,
   "contradicted": 17,
   "unlinked": 42,
   "strict": 0.25316455696202533,
   "strict_lower": 0.1745252603424512,
   "decided": 0.5405405405405406,
   "optimistic": 0.7848101265822784
  },
  "precision_held": {
   "n": 78,
   "confirmed": 23,
   "contradicted": 24,
   "unlinked": 31,
   "strict": 0.2948717948717949,
   "strict_lower": 0.21065508033063454,
   "decided": 0.48936170212765956,
   "optimistic": 0.6923076923076923
  }
 }
}
```

## Edge cases (stream, all models pooled)

| Relation | Kind of case | Actions | Confirmed | Contradicted | Unlinked |
|---|---|---|---|---|---|
| related | other | 1877 | 64 | 0 | 1813 |
| part_of | other | 1095 | 16 | 667 | 412 |
| duplicate | other | 972 | 230 | 594 | 148 |
| related | siblings | 879 | 879 | 0 | 0 |
| duplicate | same-title | 863 | 115 | 494 | 254 |
| related | bump-same-lib-diff-version | 616 | 81 | 0 | 535 |
| related | both-test-failures | 470 | 12 | 0 | 458 |
| part_of | siblings | 431 | 0 | 431 | 0 |
| duplicate | bump-same-lib-diff-version | 363 | 3 | 348 | 12 |
| part_of | bump-same-lib-diff-version | 314 | 0 | 280 | 34 |
| duplicate | both-test-failures | 228 | 20 | 135 | 73 |
| duplicate | bump-same-lib-same-version | 214 | 54 | 154 | 6 |
| duplicate | siblings | 211 | 3 | 208 | 0 |
| part_of | candidate-is-parent | 203 | 203 | 0 | 0 |
| related | bump-same-lib-same-version | 92 | 13 | 0 | 79 |
| related | same-title | 82 | 7 | 0 | 75 |
| part_of | same-title | 67 | 0 | 52 | 15 |
| part_of | bump-same-lib-same-version | 47 | 0 | 35 | 12 |
| part_of | both-test-failures | 25 | 0 | 12 | 13 |
| duplicate | candidate-is-parent | 13 | 0 | 13 | 0 |
| related | candidate-is-parent | 2 | 2 | 0 | 0 |
| any | cross-project | 329 | 0 | 137 | 192 |
