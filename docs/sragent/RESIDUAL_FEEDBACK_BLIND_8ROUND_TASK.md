# Blind residual-feedback equation discovery

## Objective

Use Hamilton as an LLM-controlled outer loop for symbolic regression. Across at most
eight governed rounds, discover an autonomous second-order equation

```text
a = f(x, v)
```

from one public training trajectory. Each later PySR configuration must be designed from
the L2 memory and current-round validation, trajectory, and structured residual evidence.

This is a clean experiment. Do not request, search for, infer, or reuse any equation,
metric, configuration, intervention, finding, plan, or artifact from an earlier Hamilton
run. Do not inspect repository documentation or any workspace other than the active one.

## Public data and isolation

The only allowed data file is:

```text
input/U248_train.csv
```

The runner, never the LLM-facing editor, may read it. Use columns `x` and `v` to predict
`a`, with `t` as time. Do not inspect raw CSV rows. Use the complete file and reserve the
contiguous final 20% as internal validation. Do not access private test or OOD data.
Tier 0 internal validation is the highest evidence available in this experiment.

## Frozen round-1 baseline

Round 1 must use exactly:

- `data.max_rows=null`;
- `data.search_stride=5`;
- `data.standardize_search=false`;
- `data.validation_fraction=0.2`;
- binary operators `+`, `-`, `*`;
- unary operators `square`, `cube`;
- `search.niterations=500`;
- `search.max_evals=12000`;
- `search.populations=8`;
- `search.population_size=32`;
- `search.tournament_selection_n=12`;
- `search.maxsize=31`;
- `search.parsimony=0.001`;
- `search.random_state=42`;
- `search.top_k=10`;
- no template expression;
- candidate ranking over at most 10 candidates with weights
  `validation_nrmse=1.0`, `trajectory_nrmse=1.0`, `complexity=0.05`;
- candidate failure penalty `100.0`;
- short ODE enabled for `x` and `v`, duration 10 seconds, 1000 points, state limit
  1000000;
- residual diagnostics enabled with `max_lag=50`, `feature_bins=4`, `phase_bins=8`,
  and `high_frequency_fraction=0.25`.

This is a search baseline, not a supplied equation prior.

## Adaptive rounds

For each round after Round 1:

1. read only active-workspace `task.md`, `plan.md`, and `findings.md`;
2. use the previous `EVO_RESIDUAL_FEEDBACK`, failed gates, trajectory evidence, and
   incumbent comparison to state a falsifiable causal hypothesis;
3. change exactly one supported `data`, `search`, or `verification` leaf field;
4. predict an observable validation-residual change and record an alternative
   explanation;
5. retain every frozen control below.

Frozen controls for all eight rounds:

- training file, allowed-file list, feature/target/time columns;
- complete-row use, search stride, validation fraction and contiguous split;
- `search.max_evals=12000`;
- `search.random_state=42`;
- candidate-ranking settings and weights;
- short-ODE settings;
- all residual-diagnostic settings;
- no private test/OOD access.

Do not choose `search.max_evals`, the random seed, output paths, experiment IDs, ranking
weights, ODE settings, or residual-diagnostic settings as adaptive interventions.

## Promotion and residual-feedback contract

Every round must:

- produce a completed result with enabled, completed residual diagnostics;
- separate execution success, score improvement, promotion validity, and scientific
  success;
- append an exact current-round `EVO_RESIDUAL_FEEDBACK` block to `findings.md`;
- report the strongest validation state dependence and strongest reported temporal
  autocorrelation with their numeric values;
- give at least one alternative explanation and one limitation;
- link `next_strategy.residual_evidence` to the same frozen current-round result;
- when continuing, write a complete `EVO_NEXT_ROUND` contract with one configuration
  leaf, expected residual change, success threshold, and falsification condition.

Residual structure is diagnostic evidence, not proof of a unique missing term.

## Scientific gates

Solver completion alone is not scientific success. A final success claim requires all:

- finite pointwise predictions and a completed, bounded 10-second rollout;
- at least one nonlinear term;
- validation R-squared at least 0.65;
- scientific score below 0.70;
- defensible evidence for including or excluding each available state variable;
- no test/OOD leakage;
- calibrated claims that do not turn a single-run observation into a physical law.

If the eight-round limit is reached without all gates passing, retain the best valid
incumbent, report scientific failure honestly, and do not invent a ninth-round contract.
