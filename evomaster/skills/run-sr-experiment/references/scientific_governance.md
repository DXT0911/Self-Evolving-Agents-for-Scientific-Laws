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
  "scale_diagnostics": {
    "method": "standardized_feature_effect",
    "raw_coefficient_comparison": false,
    "evidence": "diagnostics.linear_raw_features.scale_aware.standardized_effect"
  },
  "promotion_gates": [
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
    "config_field": "search.max_evals",
    "expected_effect": "directional observable effect",
    "risks": ["confound or numerical risk"],
    "falsification": "observable result that rejects the hypothesis"
  }
}
<!-- EVO_SCIENTIFIC_DECISION_END -->
```

## Incumbent

Scientific score is minimized. Compare the new selected score with every prior completed
result. Use `initialize` in the first round, `promote` only for a strictly lower score
whose `promotion_gates` all pass, and otherwise `retain` the earlier best result. A new
equation is not automatically the incumbent. Promotion gates express minimum candidate
validity; `scientific_gates` express the task's stricter final-success criteria.

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
and falsification result. Adding division or other unstable operators must mention
singularity/domain risks.

Solver completion alone is not scientific success. A success decision requires every
task-specific gate to pass with quantitative evidence and `solver_completion_only=false`.
