# SR Agent experiment index

Chinese translation: [`README.zh-CN.md`](README.zh-CN.md).

Each directory here is a versioned experiment package. It should contain its own research
question, protocol, manifest or task specification, offline validation, and compact report.
Generated inputs, launch bundles, checkpoints, and complete run workspaces remain ignored.

## Current experiments

| Experiment | Status | Primary report |
|---|---|---|
| [`hamilton_vs_pysr_governed_search/`](hamilton_vs_pysr_governed_search/) | Public 9-arm operational gate completed; formal multi-repeat study not run | [`OPERATIONAL_GATE_STATUS_2026-07-28.md`](hamilton_vs_pysr_governed_search/OPERATIONAL_GATE_STATUS_2026-07-28.md) |

The completed gate used three public tasks, one repeat, and no private/OOD access. It is a
pilot signal, not evidence of general superiority. See the experiment README for the
frozen design, post-hoc offline diagnostics, and remaining limitations.

## Package convention

New formal experiments should use a descriptive directory and keep these roles separate:

```text
experiments/<experiment_id>/
├── README.md                current status and commands
├── PROTOCOL.md              frozen scientific comparison contract
├── manifest/config/specs    machine-readable frozen inputs
├── test_*.py                offline contract tests
├── report.md/json           compact result summary
└── generated directories    ignored locally, never source code
```

Do not rewrite an existing protocol after observing results. Corrections or new metrics
must be labelled post-hoc, or introduced in a newly versioned experiment before execution.
