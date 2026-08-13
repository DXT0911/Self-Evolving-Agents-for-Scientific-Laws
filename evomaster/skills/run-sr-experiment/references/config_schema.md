# Configuration schema

## Minimal example

```json
{
  "schema_version": 1,
  "experiment_id": "viv-u248-smoke-001",
  "data": {
    "train_file": "input/U248_train.csv",
    "allowed_files": ["input/U248_train.csv"],
    "time_column": "t",
    "feature_columns": ["x", "v"],
    "target_column": "a",
    "max_rows": null,
    "search_stride": 5,
    "standardize_search": true,
    "validation_fraction": 0.2
  },
  "search": {
    "engine": "pysr",
    "binary_operators": ["+", "-", "*", "/"],
    "unary_operators": [],
    "niterations": 250,
    "max_evals": 8000,
    "populations": 8,
    "population_size": 32,
    "tournament_selection_n": 12,
    "maxsize": 31,
    "parsimony": 0.001,
    "random_state": 42,
    "top_k": 10
  },
  "verification": {
    "short_ode": {
      "enabled": true,
      "position_column": "x",
      "velocity_column": "v",
      "duration": 5.0,
      "points": 500,
      "state_limit": 1000000
    },
    "long_horizon_dynamics": {
      "enabled": false,
      "position_column": "x",
      "velocity_column": "v",
      "duration": 60.0,
      "points": 3000,
      "steady_state_fraction": 0.4,
      "min_steady_cycles": 3.0,
      "state_limit": 1000000,
      "rtol": 1e-8,
      "atol": 1e-10,
      "large_initial_scale": 2.0,
      "stationary_amplitude_fraction": 0.001,
      "zero_initial_policy": "report_only",
      "amplitude_relative_tolerance": 0.2,
      "frequency_relative_tolerance": 0.1,
      "stationarity_relative_tolerance": 0.15,
      "attractor_relative_tolerance": 0.2
    },
    "candidate_ranking": {
      "enabled": true,
      "max_candidates": 10,
      "weights": {
        "validation_nrmse": 1.0,
        "trajectory_nrmse": 1.0,
        "complexity": 0.05,
        "long_horizon_penalty": 0.0
      },
      "failure_penalty": 100.0
    },
    "residual_diagnostics": {
      "enabled": true,
      "max_lag": 50,
      "feature_bins": 4,
      "phase_bins": 8,
      "high_frequency_fraction": 0.25
    }
  },
  "output": {
    "result_file": "history/round1/results/viv-u248-smoke-001.json",
    "run_directory": "history/round1/results/viv-u248-smoke-001-pysr"
  }
}
```

## Validation rules

- Paths are relative to the current workspace and cannot escape it.
- `train_file` must appear exactly in `allowed_files`.
- Required columns must exist and contain finite numeric values after row selection.
- `max_rows=null` reads the complete allowed training file.
- `search_stride` samples uniformly through the discovery block for PySR only; all reported
  metrics still use every row.
- `standardize_search=true` computes means and population standard deviations from the
  discovery block only, lets PySR search `z_target = g(z_features)`, and automatically
  restores every candidate to the original variables and target units before metrics and
  ODE verification. Validation rows never influence the transform.
- Rows remain time ordered. The final `validation_fraction` is the validation block.
- `niterations`, `max_evals`, `populations`, `population_size`, `maxsize`, and ODE duration must be positive.
- `tournament_selection_n` must be smaller than `population_size`.
- PySR runs with `deterministic=true` and `parallelism="serial"`.
- Candidate ranking weights must be non-negative and `max_candidates <= top_k`.
- Long-horizon dynamics is optional and disabled for historical configurations. When enabled,
  it requires exactly position and velocity features, at least 64 integration points, an
  explicitly frozen steady-state fraction in `[0.1, 0.5]`, integration tolerances, initial-state
  scale, and all scientific tolerances. The deterministic controller evaluates the public
  contiguous validation reference plus observed, exact-zero, and discovery-scale large initial
  conditions. `zero_initial_policy` must explicitly choose whether the exact-zero rollout is
  diagnostic-only (appropriate when zero is an invariant equilibrium) or must converge to the
  same attractor. `stationary_amplitude_fraction` defines the equilibrium-amplitude threshold
  relative to the discovery-block robust position scale, so decayed equilibria are not judged
  against machine epsilon alone. The evaluator emits no pointwise rollout arrays.
- `long_horizon_penalty` defaults to zero, preserving existing scientific scores. A future
  confirmatory configuration must freeze a non-zero value before results are observed if the
  long-horizon verdict is intended to affect candidate selection. Successful integrations use
  the mean of continuous reference, stationarity, and attractor-error components; the configured
  failure penalty is reserved for catastrophic integration failure. This preserves a useful
  search gradient among scientifically incomplete but numerically stable candidates.
- Residual diagnostics default to enabled. `feature_bins` must be 2-10, `phase_bins`
  4-36, `max_lag` positive, and `high_frequency_fraction` in `(0, 0.5]`.
- Governed Hamilton rounds must explicitly keep residual diagnostics enabled. Promotion
  closure rejects a round unless completed validation diagnostics are faithfully
  promoted into `findings.md` and linked to the next strategy.
- Residual reference scales and state-bin boundaries are fitted on the discovery block
  only. Validation reuses them and never changes the diagnostic reference.
- Result and PySR run directories must stay inside the workspace.
- Non-validation executions reserve `search.max_evals` in
  `.hamilton_evaluation_ledger.json` before PySR starts. Reservations are never refunded
  after failure, rejection, interruption, or replay; `--validate-only` does not reserve.
- When `.hamilton_search_control.json` enables dynamic budgeting, `search.max_evals` in
  the authored JSON is only a proposal. The runner records and executes a deterministic
  effective allocation based on search-space size, recent stagnation, remaining
  cumulative budget, and the minimum reserve for future rounds.
- After a ledger exists, its cumulative limit may only be increased by an explicit
  controller configuration change. Each increase is recorded in
  `budget_limit_history`; decreasing or removing the limit is rejected.
- Adaptive `roundN` validation, for `N > 1`, uses the baseline named in
  `.hamilton_search_state.json`, enforces the configured trust-region step and maximum
  distance from the incumbent anchor, and excludes controller-owned `search.max_evals`
  from scientific configuration differences.

## Output

The result JSON contains:

- schema, experiment ID, status and timestamps;
- normalized configuration and data fingerprints;
- row ranges and pointwise metrics;
- a diagnostic-only linear fit of the raw variables, including feature standard
  deviations and standardized effects for cross-scale comparison;
- PySR candidates with both `search_space_equation` (standardized coordinates when enabled)
  and `simplified_equation` (original variables/units), train/validation metrics, and
  individual ODE checks;
- selected-candidate residual summaries in original target units: distribution,
  state/absolute-state correlations, train-defined feature bins, autocorrelation,
  Durbin-Watson statistic, trend, frequency concentration, and—when position/velocity
  are configured—standardized-radius and phase bins;
- the selected search-space and original-unit equations, scientific score, and selection method;
- optional public Tier-0 long-horizon summaries: robust steady amplitude, detrended-window FFT
  frequency, zero/large-initial-condition behavior, stationarity, attractor consistency,
  structured failure classes, and the ranking penalty;
- engine telemetry sourced from SymbolicRegression `SearchState.num_evals`, with every
  logged Pareto checkpoint re-evaluated on the frozen validation block to form a
  best-so-far validation-NRMSE curve; the raw JSONL stays in the ignored PySR run directory;
- runtime and environment versions;
- structured error information on failure.

The command prints a compact JSON summary between:

```text
===SR_EXPERIMENT_SUMMARY_BEGIN===
...
===SR_EXPERIMENT_SUMMARY_END===
```
