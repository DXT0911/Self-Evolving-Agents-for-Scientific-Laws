# Hamilton configuration catalog

`config.yaml` is the canonical development entry point. It enables benchmark isolation,
literature grounding, the standard SR runner, scientific governance, and controller-side
PySR preflight. It is not yet a frozen formal-experiment configuration.

All provider credentials must come from `${HAMILTON_API_KEY}`. Never commit a literal key.

## Reusable development configurations

| File | Purpose | Status |
|---|---|---|
| `config.yaml` | Current integrated Hamilton development entry | Canonical development config |
| `config_no_pysr.yaml` | Prompt/closure debugging without PySR | Diagnostic only; not a benchmark |
| `config_low_budget.yaml` | One-round low-budget smoke workflow | Historical smoke config |
| `config_adaptive.yaml` | Early adaptive three-round workflow | Superseded by stricter governance |

## Historical run and recovery configurations

The following files preserve the settings used while developing the multi-round and
Promotion recovery paths. They depend on artifacts inside a particular run workspace and
must not be launched from a clean template workspace:

- `config_multiround_test.yaml`;
- `config_controlled_long.yaml`;
- `config_promotion_resume.yaml`.

Their relative `resume_completed_result` or `start_round` settings are evidence of the
original workflow, not a portable resume contract. A future formal configuration must use
an explicit validated run workspace and a frozen budget.

## Prompt locations

Runtime prompt paths are resolved from `configs/hamilton/` into
`playground/hamilton/prompts/`. Copies under `configs/hamilton/prompts/` are retained for
the repository's existing layout and must remain byte-equivalent to their runtime copies.

## Experiment JSON examples

`experiments/viv_u248_smoke.json` is a preserved low-budget runner input. It intentionally
lives outside the workspace template so it cannot seed an Agent run with a search template.
To reproduce that smoke workflow manually, copy it into a disposable run workspace before
invoking the standard runner. It is not evidence of scientific success.
