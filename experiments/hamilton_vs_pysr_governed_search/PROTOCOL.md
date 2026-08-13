# Preregistered comparison protocol

Chinese translation: [`PROTOCOL.zh-CN.md`](PROTOCOL.zh-CN.md).

## 1. Research question

Under matched public data, initial PySR search space, cumulative evaluations, candidate
evaluation, and paired seeds, does the current governed Hamilton controller improve over
fixed PySR in:

1. terminal validation quality;
2. cross-repeat stability;
3. best-so-far quality per cumulative evaluation?

The experiment does not compare the current controller with an older Hamilton.

## 2. Hypotheses

### Primary null hypothesis

At a matched cumulative PySR evaluation budget, governed Hamilton has no improvement over
ordinary PySR in task-level terminal validation quality or anytime efficiency.

### Secondary null hypotheses

- Governed Hamilton does not reduce cross-repeat dispersion or catastrophic failures.
- Governed Hamilton does not improve exact/equivalent recovery on hidden-ground-truth tasks.
- Governed Hamilton does not improve VIV public contiguous-tail validation.

No result from this public-data experiment establishes private/OOD generalization or a
true VIV physical law.

## 3. Experimental arms

### `ordinary_pysr`

- One uninterrupted PySR search.
- Frozen configuration for the task.
- Runs only after its paired Hamilton run and receives Hamilton's realized cumulative
  budget `B_r`, where `B_r <= B`.
- Uses the repeat's primary seed.
- No LLM and no adaptive configuration changes.

### `fixed_schedule_pysr`

- Runs only after the paired Hamilton budget trace is frozen.
- Replays Hamilton's realized per-episode evaluation allowances and seed bundle exactly.
- Restarts PySR each episode but keeps the scientific search configuration fixed.
- No LLM.

This arm distinguishes search-control benefit from restart or seed-diversification benefit.

### `governed_hamilton`

- Starts from the same initial PySR configuration.
- Runs first and receives controller-determined episode allowances bounded by cumulative
  ceiling `B`.
- The LLM may propose only controller-approved search configuration changes.
- Incumbent retention, trust region, rollback, cumulative ledger, dynamic allowance,
  evidence memory, Promotion, and closure remain deterministic controller responsibilities.

All three arms use the same deterministic candidate evaluator. The LLM never accepts a
scientific candidate directly.

## 4. Fairness contract

The following are equal within each task and paired repeat:

- public dataset bytes and data fingerprint;
- train/validation split;
- target and feature columns;
- initial PySR variables, operators, complexity ceiling, population settings, and parsimony;
- total cumulative PySR evaluations;
- candidate table size and evaluator;
- numerical tolerances and scientific gates;
- seed bundle where the arm has multiple episodes;
- code commit, Python/PySR/Julia versions, and hardware allocation.

Controller-owned `search.max_evals` may differ by Hamilton episode only according to the
frozen dynamic-allocation rule. After Hamilton finishes, the controller exports a
SHA-256-frozen trace containing only allowances and seeds. If their realized sum is
`B_r <= B`, ordinary PySR receives `B_r` continuously and fixed-schedule PySR replays the
same episode allowances. Candidate equations, scores, residuals, and L2 memory are never
copied into either baseline.

LLM tokens are not converted into PySR evaluations. They are reported separately.

## 5. Dataset families

The pilot contains eleven planned tasks:

- six blind, known-ground-truth static symbolic-regression tasks;
- four known-ground-truth dynamical derivative tasks;
- one public VIV task, initially U248.

The exact external task identifiers must be frozen before launch. Static and dynamic
ground truth remains controller-visible but is not copied into the Agent workspace.

VIV U248 is one real-data task, not evidence for broad generality. The other public wind
speeds are reserved for expansion after the pilot protocol is stable; they are treated as
one correlated benchmark family in aggregate analysis.

## 6. Repeats and seeds

The preparation manifest defines three paired pilot repeats. Each repeat contains:

- one primary seed for ordinary PySR;
- a three-seed episode bundle shared by fixed-schedule PySR and Hamilton.

The seed plan is immutable after the first scientific result is observed. A formal study
should use at least five paired repeats after the pilot verifies runtime and contracts.

LLM stochasticity is recorded separately through provider, model, temperature, request
metadata when available, and run timestamp. It must not be described as fully seeded
unless the provider guarantees that property.

## 7. Outcomes

### Common primary outcomes

1. Terminal public-validation NRMSE at paired realized budget `B_r`.
2. Anytime area under the best-so-far validation-score curve, using normalized cumulative
   evaluation fraction from 0 to 1.
3. Run success indicator: completed, finite candidate and valid evaluator output.

Lower NRMSE and anytime area are better. The exact score definition and interpolation grid
must be frozen before launch.

### Known-ground-truth outcomes

- algebraic equivalence after deterministic symbolic simplification;
- numerical equivalence on a controller-only challenge grid;
- selected-variable precision/recall;
- selected expression complexity;
- exact/equivalent recovery rate across repeats.

The hidden equation and challenge grid must not enter Agent prompts or workspaces.

### Dynamic-derivative outcomes

- derivative validation metrics;
- algebraic and controller challenge-grid equivalence for the selected derivative;
- residual structure and expression complexity.

The selected ODE-Strogatz tasks expose one derivative component at a time. They do not
support trajectory or attractor claims unless both coupled equations are discovered and a
separate joint-system evaluator is preregistered. Long-horizon metrics are not silently
added mid-pilot.

### VIV outcomes

- train and contiguous-tail validation metrics;
- current short-ODE trajectory metric;
- selected equation complexity and actual variable dependence;
- residual diagnostic status;
- no private/OOD outcome.

Finding or failing to find a velocity term is descriptive, not a universal success gate.

### Resource outcomes

- reserved and consumed PySR evaluations;
- best-so-far score versus cumulative evaluations;
- wall-clock time;
- LLM input/output tokens and Promotion attempts for Hamilton;
- rejected, failed, interrupted, replayed, and rolled-back episodes.

## 8. Statistical analysis

- Pair arms by task and repeat seed plan.
- Report every task result; do not report only aggregate winners.
- Summarize continuous outcomes with median, interquartile range, paired differences, and
  bootstrap confidence intervals across tasks.
- Report known-truth recovery as counts and paired task-level rates.
- Treat VIV wind speeds as one family rather than independent replications.
- Separate pilot results from formal results.
- Do not use a failed run's missing score as a favourable omission; apply the frozen
  failure penalty and report the failure reason.

The primary comparison is `governed_hamilton` versus `ordinary_pysr`.
`fixed_schedule_pysr` is a diagnostic baseline.

## 9. Stopping and adaptation

- Hamilton stops at its cumulative ceiling, three rounds, or a structured terminal
  failure. Its baselines then receive exactly the evaluations already reserved by
  Hamilton.
- Scientific success may stop Hamilton early only if the same deterministic success
  contract can be applied to all arms.
- Unused Hamilton ceiling is recorded and is not granted to either baseline.
- Dataset selection, metrics, gates, and seed plans cannot change after the first result.
- Pilot findings may motivate a new versioned experiment, never an in-place rewrite.

## 10. Leakage and safety

- Only public training data is used.
- No private test/OOD file, filename, raw row, reference equation, or coefficient is
  released to Hamilton.
- Ground-truth tasks use opaque task identifiers inside the Agent workspace.
- Dataset adapters produce fingerprints and compact metadata before use.
- DeepSeek and PySR/Julia remain separately permission-gated.
- A preparation manifest cannot pass launch validation.
