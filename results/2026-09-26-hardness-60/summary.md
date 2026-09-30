# Hardness test: 60 real tickets × Haiku 4.5 / Sonnet 5 (Sep 26, ~14:00)

Command (seed 0, backend `cli` = `claude -p` on the subscription, lean mode):
`python scripts/judge_eval.py --models haiku,sonnet --n 60 --k 5 --workers 4`

Sample: 60 tickets from 2025 onward, 15 each of duplicate / part_of / related / none; 328 judged pairs per model.
Truth = maintainer links in Apache Jira (a floor: maintainers miss real duplicates).

**Caveat (found in review by a teammate):** when search missed the true target, `judge_eval.py` inserted it into
the shortlist (`injected: true` on those rows), and the classes were balanced 15/15/15/15. Both make these numbers
diagnostic only: they are not the precision the agent would have on the real ticket stream.

| Model | Pair accuracy | Duplicate P / R | Part_of P / R | Related P | None P / R |
|---|---|---|---|---|---|
| Haiku 4.5 | 53.4% | 66.7 / 66.7 | 57.9 / 68.8 | 8.4% (n=143) | 94.0 / 50.5 |
| Sonnet 5 | 55.8% | 61.1 / 73.3 | 50.0 / 75.0 | 7.0% (n=128) | 95.6 / 53.7 |

Assay's verdicts on this data:
- **compare_models, Haiku instead of Sonnet: REJECT.** +90.5% cost per task; quality −2.4 pp [−5.8, +0.9].
  Caveat: measured through Claude Code, where Haiku used ~1,700 hidden thinking tokens per call and Sonnet 0.
  On the plain API Haiku doesn't think unless asked, so this is a result about our *setup*. The re-run with
  thinking off is pending.
- **auto_threshold:** no auto zone is proven for any relation (n too small). The most confident duplicate calls were
  86% right (n=7) for Haiku and 100% (n=5) for Sonnet.
- "related" precision ~8% → it stays quiet. Both models are overconfident on part_of.

`judgments.jsonl`: every judged pair (schema in `docs/SCHEMA.md`).
