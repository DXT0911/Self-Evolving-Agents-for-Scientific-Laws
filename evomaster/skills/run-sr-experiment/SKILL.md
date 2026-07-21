---
name: run-sr-experiment
description: Run deterministic, budget-bounded symbolic-regression experiments from JSON configuration. Use when an agent must discover PySR equation structures and constants from raw variables, enforce a training-data allowlist, use contiguous validation blocks, dynamically rerank multiple candidates with pointwise and ODE metrics, and save machine-readable results without writing ad-hoc experiment code.
---

# Run SR Experiment

Use the bundled runner instead of creating a new Python experiment script.

## Workflow

1. The Hamilton controller must pass its Julia/PySR preflight before the first agent
   round. For a manual runner invocation, execute
   `python playground/hamilton/core/pysr_preflight.py --timeout 180` first.
   This imports PySR and loads Julia's SymbolicRegression package without fitting,
   reading data, consuming evaluations, or calling an LLM.
2. Read `task.md`, `plan.md`, and prior result summaries.
3. Create one JSON configuration under the current `history/roundN/`. Use a new
   experiment ID. For N > 1, implement the primary change in the next-round contract.
4. Validate before spending compute:

```text
use_skill(
  skill_name="run-sr-experiment",
  action="run_script",
  script_name="run_experiment.py",
  script_args="--config experiment.json --validate-only"
)
```

5. Fix every validation error. Do not bypass data or budget checks.
6. Execute:

```text
use_skill(
  skill_name="run-sr-experiment",
  action="run_script",
  script_name="run_experiment.py",
  script_args="--config experiment.json"
)
```

7. Read the returned summary and result JSON. Compare the selected candidate with the
   diagnostic-only linear fit, inspect candidate rankings, structured residual
   diagnostics, and ODE failures, then update `trace.md`, `plan.md`, and `findings.md`.
   When scientific governance is enabled, read `scientific_governance.md` and write its
   decision block.
8. Call `finish` only after recording Discovery, Verification, Promotion, and limitations.
   Use `task_completed="false"` when another research round is required.

## Rules

- Put all choices in JSON; never edit or copy the runner.
- List every permitted input in `data.allowed_files`. The runner rejects a training file outside this list or workspace.
- Never open tabular data with an LLM-facing editor. Let this local runner read it and use
  only the machine-readable result or compact console summary.
- Use a contiguous tail block for internal validation. Never random-split time series.
- Set `data.max_rows` to `null` for the complete file. Use `data.search_stride` to sample
  across the entire discovery block while calculating reported metrics on every row.
- Keep test and OOD files out of `allowed_files` during search and model selection.
- Let PySR discover structures and constants from the configured variables. Do not add a
  known target equation's terms as engineered input features.
- When feature or target scales differ materially, prefer `data.standardize_search=true`.
  The runner fits the transform on the discovery block only, searches in standardized
  coordinates, and restores candidates to original variables and target units before
  validation and ODE checks. Treat `search_space_equation` as an internal representation;
  report and interpret `simplified_equation` as the physical law.
- Enable `verification.candidate_ranking` for scientific runs. Treat its linear raw-feature
  fit as a pipeline diagnostic only, never as a discovered equation.
- Keep `verification.residual_diagnostics` enabled for scientific runs. Interpret
  validation residual structure before changing the next search field:
  state/absolute-state dependence suggests unresolved state structure; autocorrelation,
  trend, or narrow spectral peaks suggest unresolved dynamics or correlated measurement
  error; upper-band spectral power may reflect derivative-estimation noise. None uniquely
  identifies a missing term.
- Never translate one residual correlation or bin pattern directly into an engineered
  feature or equation template. State at least one alternative explanation and make the
  next intervention falsifiable.
- Treat `status="completed"` as execution success, not scientific success. Inspect metrics and verification results.
- Minimize `scientific_score`; retain the earlier incumbent unless a new result is strictly
  better and passes the applicable scientific gates.
- Compare standardized effects or term contributions across variables, never raw
  coefficients with different units.
- Calibrate causal language to the evidence and make every next strategy falsifiable.
- If `status="failed"`, use `error.type`, `error.message`, and `error.stage` to change the next configuration.
- Keep `search.random_state`, deterministic serial execution, config, result JSON, and Git revision together for reproducibility.
- When `.hamilton_budget.json` exists, the runner rejects an experiment that would exceed
  its cumulative `max_total_evals`.

Read [config_schema.md](references/config_schema.md) when creating or changing a configuration.
For adaptive runs, also read [adaptive_rounds.md](references/adaptive_rounds.md).
When `experiment.scientific_governance=true`, read
[scientific_governance.md](references/scientific_governance.md).
Before claiming cross-condition or final generalization, read
[ood_protocol.md](references/ood_protocol.md). Tier 1--3 evaluation is a
controller-only operation on a frozen candidate; never add sealed data to the runner.
