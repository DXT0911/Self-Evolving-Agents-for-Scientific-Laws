# Tiered OOD protocol

OOD evaluation is a controller action on a frozen candidate. The research agent must
never add sealed files to an experiment configuration or invoke the private evaluator.

| Tier | Question | Eligible model | Feedback policy |
| --- | --- | --- | --- |
| Tier 0 | Does the equation generalize to the contiguous tail of the discovery record? | Any candidate | Available in every discovery round |
| Tier 1 | Does it generalize at the same operating condition under a different initial condition? | Condition-specific or global equation | Bounded development summary |
| Tier 2 | Does one shared law generalize to an excluded operating condition? | Global original-unit equation containing the operating variable | Bounded promotion summary |
| Tier 3 | Does the frozen global law generalize to external regimes? | Global original-unit equation containing the operating variable | One-shot final attestation only |

Tier 0 is performed by the standard experiment runner. Tiers 1--3 are performed by the
controller-side OOD evaluator, not by this Skill or by the LLM-facing editor.

## Candidate freeze

Finish search and incumbent selection without using the target OOD tier, then freeze the
selected result JSON files. The controller records each result's SHA-256 and a canonical
`freeze_id`. Evaluation must reject a bundle if a source result changes afterward.

A condition-specific equation is eligible only for Tier 1 at that same condition. Tier 2
and Tier 3 require one shared equation that explicitly accepts the operating variable
and was fitted using multiple declared training conditions. Never apply coefficients
from one condition-specific fit to another condition and call that OOD generalization.

## Access accounting and feedback

Every private evaluation begins by writing a ledger entry. A failed or interrupted
attempt still consumes one access. The private manifest sets the maximum total access
count for each tier.

Tier 1 and Tier 2 may release aggregate metrics for development. Once released, those
records have influenced model selection and cannot be presented as untouched final
evidence. Tier 3 is `final_only`: it releases no adaptive feedback, may be used once, and
must be followed by finalization rather than another research round.

Finalization writes a public attestation and a workspace lock. A locked workspace cannot
run further adaptive Hamilton rounds.

## Controller command sequence

Run these commands manually or from trusted orchestration, never from the research agent:

```text
python -m playground.hamilton.core.ood_evaluator freeze \
  --workspace <workspace> --result <completed-result-relative-path> \
  --output <private-root>/frozen_candidate.json

python -m playground.hamilton.core.ood_evaluator evaluate \
  --tier tier1 --workspace <workspace> --private-root <private-root> \
  --bundle <private-root>/frozen_candidate.json \
  --output <private-root>/tier1_result.json \
  --release-summary <workspace>/history/ood_tier1_summary.json
```

Tier 2 uses the same `evaluate` command with its own bounded release summary. Tier 3 must
omit `--release-summary`; after it completes, use `finalize` to create the public
attestation and workspace lock.

## Required evidence

For each evaluated condition report aggregate pointwise MSE, RMSE, MAE, NRMSE, and
R-squared. Also report trajectory integration status, position RMSE/NRMSE, final-state
error, and tail-amplitude relative error. Released summaries may identify the public
condition but must not contain sealed file paths, raw rows, or private labels.

Pointwise success cannot override failed or inaccurate trajectory integration. OOD
failure can indicate a poor equation, a validity boundary, or a regime change; it does
not by itself identify one missing algebraic term.

## Agent-facing record

`plan.md` should record the highest completed tier, the `freeze_id`, released aggregate
evidence, whether that evidence was used for adaptation, and the next readiness criterion
or blocker. Never invent an unavailable tier result. If Tier 2 is blocked because only
condition-specific models exist, make discovery of a shared operating-variable equation
an explicit research objective.
