# Frozen Hamilton v4 development pilot

Task `static_s01`, pair `repeat_1`, seed `8201`. Development-only evidence.

Use only `input/data.csv` through the governed standard runner. Do not read raw rows,
identify the hidden source, search literature, access private/OOD data, or evaluate a
candidate outside the runner.

The feature columns (x1, x2) are opaque predictors and y is the target. t is a deterministic ordering index and is not a scientific input.

Run exactly three governed rounds of 1,000 requested evaluations. Preserve the seed,
worker, population, operators, maxsize, run directory, and warm PySR state. The frozen
deterministic binding policy owns action selection. The LLM may state a structural
hypothesis but may not override its action, patch, candidate retention, rollback, or
budget. A binding `continue` is an authorized no-op continuation.

Round 1 must use this exact configuration:

```json
{
  "data": {
    "allowed_files": [
      "input/data.csv"
    ],
    "feature_columns": [
      "x1",
      "x2"
    ],
    "max_rows": null,
    "search_stride": 10,
    "standardize_search": false,
    "target_column": "y",
    "time_column": "t",
    "train_file": "input/data.csv",
    "validation_fraction": 0.2
  },
  "experiment_id": "v4_pilot_hamilton__static_s01__repeat_1__round1",
  "output": {
    "result_file": "history/round1/results/result.json",
    "run_directory": "session/pysr"
  },
  "schema_version": 1,
  "search": {
    "binary_operators": [
      "+",
      "-",
      "*",
      "/"
    ],
    "engine": "pysr",
    "max_evals": 1000,
    "maxsize": 31,
    "niterations": 1000,
    "parsimony": 0.001,
    "population_size": 32,
    "populations": 8,
    "random_state": 8201,
    "top_k": 10,
    "tournament_selection_n": 12,
    "unary_operators": [
      "sin",
      "cos",
      "exp"
    ]
  },
  "search_session": {
    "compatible_change_fields": [
      "search.parsimony"
    ],
    "final_round": false,
    "mode": "warm_start",
    "round": 1,
    "round_action": "initialize",
    "session_id": "v4-pilot-static_s01-repeat_1"
  },
  "verification": {
    "candidate_ranking": {
      "enabled": true,
      "failure_penalty": 100.0,
      "max_candidates": 10,
      "weights": {
        "complexity": 0.05,
        "trajectory_nrmse": 0.0,
        "validation_nrmse": 1.0
      }
    },
    "residual_diagnostics": {
      "enabled": true,
      "feature_bins": 4,
      "high_frequency_fraction": 0.25,
      "max_lag": 50,
      "phase_bins": 8
    },
    "short_ode": {
      "enabled": false
    },
    "structural_diagnostics": {
      "enabled": true
    }
  }
}
```
