# Hamilton configuration catalog

`config.yaml` is the canonical development entry point. It enables benchmark isolation,
literature grounding, the standard SR runner, scientific governance, and controller-side
PySR preflight. It is not yet a frozen formal-experiment configuration.

`experiment.promotion.max_tokens` limits the separate `PromotionExp` Agent run, while
`max_attempts` bounds resumptions. When a global token budget is present, the Playground
reserves the Promotion allowance before starting `RoundExp`.

All provider credentials must come from `${HAMILTON_API_KEY}`. Never commit a literal key.

## Supported entries

| File | Purpose | Status |
|---|---|---|
| `config.yaml` | Current integrated Hamilton development entry | Canonical development config |
| `config_no_pysr.yaml` | Prompt/closure debugging without PySR | Diagnostic only; not a benchmark |
| `config_governed_pysr_public_pilot.yaml` | Frozen governed-Hamilton arm for the public Hamilton-vs-PySR pilot | Permission-gated formal pilot |

`config_no_pysr.yaml` creates only labelled protocol-debug artifacts. It cannot establish
a candidate equation, benchmark performance, or scientific success.

`config_governed_pysr_public_pilot.yaml` is tied to
`experiments/hamilton_vs_pysr_governed_search/pilot_manifest.yaml`. It must not run unless
that manifest passes launch validation after separate DeepSeek and PySR/Julia authorization.

## Frozen historical configurations

The following files preserve earlier smoke, adaptive, controlled-run, or recovery
settings. They are retained so dated research records remain interpretable:

- `config_low_budget.yaml`;
- `config_adaptive.yaml`;
- `config_multiround_test.yaml`;
- `config_controlled_long.yaml`;
- `config_promotion_resume.yaml`;
- `config_residual_blind_8round.yaml`.

Do not start a new experiment from these files. Some include relative
`resume_completed_result` or `start_round` settings tied to a particular workspace; the
others predate the current search-control contract. A formal experiment must use a new
descriptive configuration, an explicit validated workspace, and a frozen cumulative
budget.

## Prompt locations

Runtime prompt paths are resolved into `playground/hamilton/prompts/`. That directory is
the single source of truth. Do not create prompt copies under `configs/hamilton/`.

## Experiment JSON examples

`experiments/viv_u248_smoke.json` is a preserved low-budget runner input. It intentionally
lives outside the workspace template so it cannot seed an Agent run with a search template.
To reproduce that smoke workflow manually, copy it into a disposable run workspace before
invoking the standard runner. It is not evidence of scientific success.

See `playground/hamilton/DEVELOPMENT.md` for ownership boundaries, test commands, and the
workflow for adding a formal experiment.
