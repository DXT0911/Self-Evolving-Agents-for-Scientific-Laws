# SR Agent documentation index

The documents in this directory serve different purposes. A dated experiment task or
audit is evidence about one run, not the current runtime contract.

## Current contracts

- `RESEARCH_PROTOCOL.md` — authoritative research and benchmark-isolation protocol.
- `RESEARCH_PROTOCOL.zh-CN.md` — Chinese protocol translation.
- `../../playground/hamilton/DEVELOPMENT.md` — collaborator development guide.
- `../../playground/hamilton/README.md` — Hamilton architecture and runtime behavior.
- `../../playground/hamilton/TODO.md` — implementation and research backlog.

## Dated handoffs and summaries

Files whose names contain a date are snapshots. Use the newest applicable handoff for
context, but verify claims against Git history, configs, and run evidence before resuming
an experiment.

## Historical experiment specifications

The following files preserve earlier acceptance, smoke, recovery, and controlled-run
procedures:

- `ADAPTIVE_MULTI_ROUND_TASK.md`
- `CONTROLLED_LONG_RUN_TASK.md`
- `LOW_BUDGET_SMOKE_TASK.md`
- `RESIDUAL_FEEDBACK_BLIND_8ROUND_TASK.md`
- `SINGLE_ROUND_CLOSURE_TASK.md`
- `SINGLE_ROUND_SCIENTIFIC_TASK.md`

Do not treat them as default launch instructions. Their matching configs may depend on a
specific run workspace or a historical budget.
