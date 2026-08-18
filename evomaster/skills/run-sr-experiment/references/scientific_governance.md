# Scientific governance

When `experiment.scientific_governance=true`, maintain exactly one machine-readable
decision block in `plan.md` after every experiment:

```text
<!-- EVO_SCIENTIFIC_DECISION_BEGIN -->
{
  "incumbent": {
    "result_file": "history/round1/results/example.json",
    "action": "initialize"
  },
  "claims": [
    {
      "statement": "Observed result",
      "strength": "observation",
      "evidence": ["result path plus metric"],
      "alternatives_tested": 0
    }
  ],
  "protocol_evidence": {
    "valid_result_files": [
      "history/round1/results/...",
      "history/round2/results/..."
    ],
    "invalid_attempts_used_as_scientific_evidence": false
  },
  "scale_diagnostics": {
    "method": "standardized_feature_effect",
    "raw_coefficient_comparison": false,
    "evidence": "diagnostics.linear_raw_features.scale_aware.standardized_effect"
  },
  "search_advancement_gates": [
    {
      "name": "candidate validity gate",
      "passed": false,
      "evidence": "quantitative metric and threshold"
    }
  ],
  "scientific_gates": [
    {
      "name": "task-specific validation",
      "passed": false,
      "evidence": "metric and threshold"
    }
  ],
  "solver_completion_only": false,
  "next_strategy": {
    "diagnosed_failure": "specific failed gate",
    "evidence": "result path plus metric",
    "action": "modify",
    "residual_evidence": {
      "result_file": "history/round1/results/example.json",
      "finding": "state_dependence",
      "observed": "validation residual has its strongest state correlation with v at 0.31"
    },
    "config_field": "search.maxsize",
    "config_patch": {"search.maxsize": 31},
    "expected_effect": "directional observable effect",
    "alternative_explanation": "derivative estimation bias could create the same pattern",
    "expected_residual_change": "absolute validation residual-v correlation decreases",
    "risks": ["confound or numerical risk"],
    "falsification": "observable result that rejects the hypothesis"
  }
}
<!-- EVO_SCIENTIFIC_DECISION_END -->
```

## Incumbent

Scientific score is minimized. Compare the new selected score with every prior completed
result. Use `initialize` in the first round, `promote` only for a strictly lower score
whose `search_advancement_gates` all pass, and otherwise `retain` the earlier best result.
A new equation is not automatically the search incumbent.

`search_advancement_gates` and `scientific_gates` have different authority:

- search advancement gates express minimum candidate validity and decide whether an
  incremental improvement becomes the new search anchor;
- scientific gates express the task's stricter final-success criteria and alone govern
  `task_completed=true`.

A candidate may therefore become the search incumbent without satisfying final scientific
success. Historical `promotion_gates` blocks remain readable for recovery compatibility,
but new decisions must use `search_advancement_gates`.

## Controller evidence memory

After a governed round closes, the controller updates
`.hamilton_evidence_memory.json`. The LLM must not edit this file.

- Strong memory contains scoped numerical search outcomes, exact residual observations,
  and incumbent initialization/promotion history. A retained challenger is recorded only
  as the strong observation that it failed to advance under the tested controls, not as
  proof that its changed field is universally harmful.
- Weak memory contains untested causal hypotheses and non-advancing near-miss candidates.
  It may prioritize exploration but cannot directly exclude variables/operators, alter
  the incumbent, or override trust-region and numerical gates.
- Every entry cites a frozen result path and SHA-256. Replaying the same closed round
  updates rather than duplicates its records. Protocol-invalid or failed-governance
  attempts are rejected before memory writing.

The controller injects a compact read-only view of this memory into the next-round
directive. Original result JSON remains the source of truth.

## Claim strength

Use only `observation`, `hypothesis`, `supported`, or `confirmed`.

- `observation`: directly recorded result.
- `hypothesis`: proposed explanation not yet tested.
- `supported`: intervention produced the predicted evidence but alternatives remain.
- `confirmed`: reserve for at least two supporting evidence items and at least one tested
  alternative explanation.

Negative evidence against one intervention does not confirm a different root cause.

## Scale-aware diagnostics

Never rank variables by raw coefficient magnitude across different units. Prefer:

- `standardized_feature_effect` from the runner's diagnostic;
- `term_contribution` evaluated over the observed data domain;
- `dimensional_analysis`;
- `not_applicable`, with a concrete explanation in `evidence`.

The linear diagnostic remains a pipeline diagnostic, never a discovered equation.

## Residual diagnostics

Use `verification.residual_diagnostics.validation` to diagnose why a candidate fails.
Report the strongest state dependence and temporal dependence with their numeric values.
Compare train and validation using the training-fitted scale and bin boundaries.

Treat residual patterns as non-unique evidence:

- state dependence can reflect missing structure, biased derivatives, or restricted state coverage;
- autocorrelation or spectral peaks can reflect missing dynamics, forcing, delay, or measurement processing;
- high-frequency power can reflect numerical differentiation noise.

Do not claim a specific missing algebraic term from one diagnostic. Connect the next
single-field intervention to a failed gate, state an alternative explanation, and define
what residual change would falsify the hypothesis. Residual diagnostics are not included
in `scientific_score` unless a future scoring contract explicitly adds them.

Every governed round must append this machine-readable block to `findings.md`; retain
older blocks and append the current round as the last block:

```text
<!-- EVO_RESIDUAL_FEEDBACK_BEGIN -->
{
  "round": 1,
  "result_file": "history/round1/results/example.json",
  "strongest_state_dependence": {"signal": "v", "value": 0.31},
  "strongest_temporal_dependence": {"lag": 5, "value": 0.42},
  "interpretation": "specific evidence-supported diagnosis without claiming a unique term",
  "alternative_explanations": ["at least one competing explanation"],
  "limitations": ["what this diagnostic cannot establish"],
  "next_testable_question": "question answered by one falsifiable next intervention"
}
<!-- EVO_RESIDUAL_FEEDBACK_END -->
```

The values must exactly reproduce the selected result's
`verification.residual_diagnostics.validation.state_dependence.strongest_absolute_correlation`
and `temporal_structure.strongest_reported_autocorrelation`. Closure rejects disabled or
missing diagnostics, stale round numbers, mismatched values, missing alternatives, or
missing limitations.

When research continues, `next_strategy.residual_evidence.result_file` must point to the
same current-round result. `finding` must be `state_dependence`, `temporal_dependence`,
`both`, or `no_material_structure`; also provide `alternative_explanation` and an
observable `expected_residual_change`. The human-readable `EVO_NEXT_ROUND` contract must
repeat the residual evidence, alternative explanation, expected residual change, and
falsification condition.

## Tiered OOD evidence

Keep contiguous internal validation (Tier 0), same-condition/different-initial-state
testing (Tier 1), excluded-operating-condition testing (Tier 2), and external-regime
testing (Tier 3) separate. Follow
[ood_protocol.md](ood_protocol.md) before making a generalization claim.

Record the frozen candidate's `freeze_id` and the highest completed tier. Tier 1 and
Tier 2 aggregate summaries may guide later interventions only within their controller
access budgets; because they influenced development, they are not untouched final
evidence. Never request private paths, raw rows, or hidden labels.

Tier 3 is a one-shot final-only evaluation. Scientific completion requires a
controller-generated Tier 3 attestation. After that attestation is finalized, do not
start another adaptive round.

## Plan quality and success

Tie the next configuration field to a failed gate and state its expected effect, risks,
and falsification result. When the controller enables no-op continuation, a justified
decision to hold the scientific configuration is also valid: set `action` to `continue`,
`config_field` to `null`, and `config_patch` to `{}` while retaining the same evidence,
alternative-explanation, residual-change, risk, and falsification requirements. The
following round must use warm-start `round_action: "continue"`; it still consumes its
authorized budget and is not an early task completion. Adding division or other unstable operators must mention
singularity/domain risks.

When dynamic budgeting is enabled, `search.max_evals` is controller-owned. Do not select
it as `next_strategy.config_field`; the runner allocates it from the cumulative ledger.
Build the next configuration from the controller-declared trust-region baseline. If the
directive requires rollback, use the stored incumbent configuration rather than the
latest failed configuration.

Solver completion alone is not scientific success. A success decision requires every
task-specific gate to pass with quantitative evidence and `solver_completion_only=false`.
