---
name: run-sr-experiment
description: Run deterministic, budget-bounded symbolic-regression experiments from JSON configuration. Use when discovering PySR equation structures from raw variables, enforcing a data allowlist, using contiguous validation blocks, reranking candidates, and saving machine-readable results without ad-hoc scripts.
---

# Run SR Experiment

Always use the bundled runner; never write a new experiment script.

## Workflow

1. Before round 1 the controller runs the Julia/PySR preflight. For manual use:
   `python playground/hamilton/core/pysr_preflight.py --timeout 180`.
2. Follow the phase. `hamilton_round`: read `task.md`, `plan.md`, prior result summaries.
   `hamilton_promotion`: read `promotion_evidence.json` only (not the full result when
   `full_result_read_required=false`); never configure/validate/rerun PySR here.
3. Round 1: write the frozen baseline under `history/round1/`. Round N>1: don't rewrite
   the full config; materialize baseline + L2 single-field patch via:
   `use_skill(skill_name="run-sr-experiment", action="run_script", script_name="prepare_adaptive_config.py", script_args="--round N")`.
4. Validate before spending compute:
   `use_skill(..., action="run_script", script_name="run_experiment.py", script_args="--config experiment.json --validate-only")`.
   Fix every error; never bypass data/budget checks.
5. Execute:
   `use_skill(..., action="run_script", script_name="run_experiment.py", script_args="--config experiment.json")`.
6. `hamilton_round`: read the summary + result JSON, compare the selected candidate with
   the linear-fit diagnostic, inspect rankings/residuals/ODE failures. Update only
   `trace.md`, then `finish(task_completed="false")`. Don't touch plan.md/findings.md or
   read scientific_governance.md.
7. `hamilton_promotion`: read `scientific_governance.md`, update trace.md/plan.md/
   findings.md, write the decision + residual-feedback blocks, then `finish`. Read the
   compact evidence + three L2 files in parallel, issue the three edits in one response,
   then finish without rereading.

## Rules

- Put all choices in JSON; never edit/copy the runner.
- List every permitted input in `data.allowed_files`; the runner rejects anything else.
- Never open tabular data with an LLM editor; use the runner's machine-readable result.
- Use a contiguous tail block for validation; never random-split time series.
- `data.max_rows=null` for the full file; `data.search_stride` samples search rows while
  metrics use every row.
- Keep test/OOD files out of `allowed_files` during search.
- Let PySR discover structures; don't engineer known-target terms as features.
- `data.standardize_search=true` when scales differ; interpret `simplified_equation`
  (not `search_space_equation`) as the physical law.
- Enable `verification.candidate_ranking`; its linear fit is a diagnostic, not a law.
- Keep `verification.residual_diagnostics` enabled (closure rejects disabled/missing/
  failed). Residual structure is non-unique: state dependence → unresolved state;
  autocorrelation/trend/narrow peaks → unresolved dynamics/noise. Never map one
  correlation directly to an engineered feature; state ≥1 alternative explanation and
  make the intervention falsifiable.
- `status="completed"` = execution success, not scientific success. Minimize
  `scientific_score`; advance the incumbent only on a strictly better result passing
  gates; keep scientific-success gates separate.
- Compare standardized effects/term contributions, never raw cross-unit coefficients.
- Calibrate causal language; make each next strategy falsifiable.
- Evidence memory is read-only: strong = scoped observations, weak = hints; never edit
  `.hamilton_evidence_memory.json` or let weak memory override gates.
- On `status="failed"`, use `error.type/.message/.stage` to change the next config.
- Keep `random_state`, serial execution, config, result, and Git revision together.
- The runner reserves `search.max_evals` before PySR via `.hamilton_evaluation_ledger.json`;
  dynamic budgeting makes this controller-owned. Every attempt retains its reservation; a
  new reservation exceeding `max_total_evals` is rejected.
- Round N>1 validates the config against the trust-region baseline (step size + anchor
  distance) before reserving evals; repeated stagnation triggers rollback. A budget limit
  may only be raised (recorded), never removed/decreased.

Read `config_schema.md` when creating/changing a config; `adaptive_rounds.md` for adaptive
runs; `scientific_governance.md` only during governed promotion; `ood_protocol.md` before
cross-condition/generalization claims (Tier 1-3 is controller-only).
