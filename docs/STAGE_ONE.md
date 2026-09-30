# Stage 1: usable local workbench

Baseline: event repository main at 8fefe93. This checkout is separate from the old device prototype.

## Run on this machine

From the event-build directory, run `powershell -ExecutionPolicy Bypass -File .\Start-Assay.ps1`.
Open http://127.0.0.1:8502. Keep the terminal open; Ctrl+C stops the app. Re-running the script restarts it.

1. Choose a recorded configuration and a proposal in Review queue.
2. Inspect both tickets, enter a note, and save an acceptance, rejection or correction.
3. Acceptance writes a local sandbox link. The receipt and count survive restart. Repeated/concurrent acceptance cannot duplicate the same proposal's link.
4. Trust explains why AUTO is disabled. Try a ticket searches locally without inference. Model check shows diagnostic cost allocations, not certification.

The SQLite database in local-state/workbench.sqlite3 is a local transactional store, not a cloud persistence design. Review and link creation commit together. No seven-state external-action workflow is implemented. The archive's old feedback mirror is not used. Cloud persistence stays in Stage 4 and must be verified before deployment. Do not deploy this local workbench as a durable multi-user cloud app.

## Freeze an experiment without calls

`.\.venv\Scripts\python.exe scripts/prepare_eval.py --fresh --n 60 --seed 1 --save-plan results/frozen-plan.json`

Then inspect the same immutable inputs with `--plan-file results/frozen-plan.json --prompt v2`. A changed prompt changes the configuration ID, not the plan. Saving refuses overwrite; content hashes detect edits. Full ordered candidate contents are retained. Targets are not injected. Missing links are unknown.

This samples the existing candidate snapshot, which is biased relative to the entire stream. The generated plan is explicitly diagnostic and does not qualify for permissions. Honest-stream retrieval, independent labeling, correction verdicts and permission receipts remain the next milestone. No model runs occurred in this build.

Prompt versions v1/v2/bad are available in judge.py; rules, backend, model and settings affect identity. Unresolved model aliases and provider defaults are explicitly unverified. Historical rows are not promoted to verified v1. Usage is retained on new judgment rows; task_cost_usd and usage repeat on pairs and must only be counted once per task.

The old judge_eval.py now resumes by task/input/config identity instead of ticket/model alone. It is still the historical injected-target diagnostic runner; use prepare_eval.py for the new zero-call planning path. Model calls are disabled by default in judge.call. Do not enable ASSAY_ALLOW_MODEL_CALLS until the owner approves the particular run and any spending limit. This milestone does not implement a monetary budget guard.

## Remaining limitations

- The original app/app.py remains the teammate's historical dashboard. The supported Stage 1 entry point is app/workbench.py.
- Legacy engine calculations and statistical certification are not used to authorize actions in the new workbench.
- Correction feedback is saved, not automatically applied or statistically validated.
- Configuration scoping does not yet demonstrate revocation of a previously earned AUTO permission; no real permission has been earned.
- Reviews are scoped to configuration. The first saved decision for a proposal is immutable in this milestone; a later audit-preserving revision workflow is pending.
- No Databricks connection, live inference, external Jira writes, commits or pushes were made.

## Commit handoff

Mohit remains the person who commits and pushes. Review `git status --short` and `git diff` inside event-build, never the old parent repository. Stage selected code, tests and docs only. Do not stage .venv, local-state, private keys or bulk input data. The event repository's original history is preserved.
