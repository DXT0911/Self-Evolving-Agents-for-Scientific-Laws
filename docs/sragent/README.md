# SR Agent documentation index

Chinese translation: [`README.zh-CN.md`](README.zh-CN.md).

The documents in this directory serve different purposes. A dated experiment task or
audit is evidence about one run, not the current runtime contract.

## Current contracts

- `REPOSITORY_MAP.md` — repository layout, ownership, and generated-artifact navigation.
- `RESEARCH_PROTOCOL.md` — authoritative research and benchmark-isolation protocol.
- `RESEARCH_PROTOCOL.zh-CN.md` — Chinese protocol translation.
- `../../playground/hamilton/DEVELOPMENT.md` — collaborator development guide.
- `../../playground/hamilton/README.md` — Hamilton architecture and runtime behavior.
- `../../playground/hamilton/TODO.md` — implementation and research backlog.

## Current experiment evidence

- `../../experiments/README.md` — versioned experiment status index.
- `../../experiments/hamilton_vs_pysr_governed_search/` — governed Hamilton versus PySR
  public comparison. Its three-task, one-repeat operational gate is complete; the planned
  formal multi-repeat study is not.

Experiment protocols, manifests, adapters, and compact reports belong in `experiments/`.
Complete workspaces, logs, checkpoints, and repeated data copies remain ignored locally.

## Dated handoffs and summaries

Files whose names contain a date are snapshots. Use the newest applicable handoff for
context, but verify claims against Git history, configs, and run evidence before resuming
an experiment.

Untracked drafts are not part of this index or the repository contract until they are
explicitly reviewed and committed.

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
