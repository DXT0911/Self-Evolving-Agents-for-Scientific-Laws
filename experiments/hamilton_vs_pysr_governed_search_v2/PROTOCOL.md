# Frozen v2 comparison protocol

## Research treatment

Every task/repeat starts from the same public bytes, opaque variables, split, initial PySR
configuration, deterministic evaluator, total requested-evaluation ceiling, and seed plan.
Reference expressions stay controller-only.

The four arms are:

- `ordinary_pysr`: one uninterrupted fixed search at the paired realized total budget;
- `fixed_schedule_pysr`: three fixed-configuration restarts replaying Hamilton's exact
  episode allowances and seeds;
- `union_schedule_pysr`: the same restarts, allowances, and seeds, with the complete frozen
  operator envelope available from episode 1;
- `governed_hamilton`: three governed episodes; the LLM may propose one permitted search
  leaf change per transition, while the controller owns validation, ledgers, incumbent,
  trust region, rollback, Promotion, and closure.

The union arm distinguishes residual-guided timing from merely having a wider operator set.

`max_evals` is recorded as a requested stopping threshold, not treated as the observed
number of evaluations. SymbolicRegression's `SearchState.num_evals` logger value is the
confirmatory efficiency axis because initialization and batched work can pass the requested
threshold. Both values are retained in every result.
No Hamilton candidate, score, residual, L2 memory, or natural-language decision enters a
baseline workspace.

## Four outcome goals

1. **Terminal accuracy:** terminal public validation NRMSE, paired Hamilton minus baseline.
2. **Recovery and reliability:** strict controller challenge-grid equivalence, variable
   precision/recall, complexity, structured completion, and frozen failure penalty.
3. **Search efficiency:** engine-measured evaluations at each best-so-far update, area under
   the right-continuous best-validation-NRMSE curve on normalized budget `[0,1]`, and first
   evaluation reaching NRMSE thresholds `0.10`, `0.05`, and `0.01` when reached.
4. **Control cost:** DeepSeek input/output/reasoning tokens, wall-clock seconds, Promotion
   attempts, and PySR evaluation overhead reported separately. Tokens never convert into
   evaluations.

The primary confirmatory comparisons are Hamilton versus ordinary PySR and Hamilton versus
fixed-schedule PySR. Hamilton versus union-schedule PySR is the mechanism diagnostic.

## Dataset phases

`dataset_split.yaml` is frozen before any v2 outcome. Previously observed `static_s01` and
`dynamic_d01` are development-only. Validation tasks may select one controller policy.
The final test tasks remain outcome-sealed until that policy and its Git commit are frozen.
After the test seal is opened, no v2 prompt, controller, operator, threshold, or budget may
change; any change creates v3.

## Search and resource contract

- public data only; no private/OOD access;
- three Hamilton episodes, maximum 12,000 requested evaluations per arm/task/repeat;
- dynamic Hamilton episode range 2,500--5,500, base 4,000, 500 quantum, with enough reserve
  for remaining episodes;
- initial binary operators `+ - * /`;
- initial unary operators `sin cos exp`;
- union envelope `sin cos exp tanh`;
- maximum one changed scientific leaf per transition and anchor distance two;
- Discovery ceiling 120,000 tokens per round;
- Promotion ceiling 60,000 tokens per round, at most two attempts, provider thinking off;
- Hamilton task/repeat ceiling 600,000 tokens;
- every launch uses persistent stdout/stderr files and fail-fast exit propagation.

The execution ceiling for all planned validation and test runs is 1,536,000 requested PySR
evaluations and 19,200,000 Hamilton tokens. These are hard maxima, not spending targets.
The execution waves are:

1. operational gate: `static_s02`, `dynamic_d02`, repeat 1, all four arms;
2. validation calibration: all four validation tasks, repeats 1--3;
3. sealed test: all four test tasks, repeats 1--5.

Wave 1 continues only if every artifact is valid, ledgers reconcile, measured-evaluation
telemetry is present, no leakage occurs, and background launch/recovery works. Scientific
performance does not rewrite Wave 1. Validation performance may select one predeclared
policy variant. Test performance never changes execution.

## Analysis

Report every task and repeat. Use paired differences, median/IQR, task-level bootstrap
confidence intervals, equivalence counts, and failure counts. Never omit failed runs; use a
frozen NRMSE penalty of 10.0 and separately report the failure class. Development,
validation, and test results are never pooled as if they were exchangeable confirmatory
replicates.

The v1 requested-boundary AUC remains historical and post-hoc. V2 confirmatory efficiency
claims require engine-measured telemetry produced during the run.
