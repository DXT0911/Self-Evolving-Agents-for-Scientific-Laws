# Public VIV Dynamics-Feedback Operational-Gate Protocol

Status: execution blocked pending supplemental replacement authorization after the invalid
2026-08-13 launch attempt recorded in `LAUNCH_ATTEMPT_2026-08-13.md`.

## Research question

Under identical public U248 bytes, contiguous split, initial PySR search space, cumulative
requested-evaluation ceiling, seed bundle, candidate pool, controller, and final evaluator, does
long-horizon dynamics feedback help Hamilton select search interventions that recover more credible
VIV dynamics than fit-only Hamilton or direct PySR?

This one-repeat operational gate tests execution and diagnostic separation. It cannot establish
general superiority, repeatability, private/OOD generalization, or statistical significance.

## Scope and order

- Task: public `viv_u248` only.
- Repeat: `repeat_1` only.
- Arms: `direct_pysr`, `fit_only_hamilton`, `dynamics_aware_hamilton`.
- Execution order after separate authorization: both Hamilton arms first under their paired frozen
  seed plan, then direct PySR with the common cumulative ceiling.
- No candidate, equation, score, residual, long-horizon result, or L2 memory crosses between arms.
- Private/OOD access is forbidden.

## Common search contract

All arms begin with the same public data, split, variables, operators, population settings,
parsimony, maximum expression size, candidate pool, and seeds recorded in `arm_specs.yaml`.
The cumulative requested-evaluation ceiling is 12,000 per arm. Each Hamilton arm uses three
controller-allocated rounds with the same deterministic bounds and seed bundle. Direct PySR uses
one uninterrupted 12,000-evaluation request with the primary seed.

Hamilton may change at most one allowed scientific leaf per round, within anchor distance two.
Budget, seeds, paths, evidence release, Promotion, rollback, closure, and memory remain controller
owned. Direct PySR has no LLM and no adaptive configuration.

## Treatment separation

`fit_only_hamilton` uses public pointwise validation NRMSE, complexity, and pointwise residual
structure during search. Short-trajectory and long-horizon evidence is not used for candidate
ranking, not projected into Promotion evidence, and not released to its LLM. It is computed only
after the arm freezes its endpoint for common final evaluation.

`dynamics_aware_hamilton` uses the same pointwise evidence plus short-ODE trajectory NRMSE and the
deterministic public Tier-0 long-horizon summary. Its search score weights are frozen as:

```text
validation_nrmse       1.00
trajectory_nrmse       1.00
complexity             0.05
long_horizon_penalty   1.00
```

The long-horizon penalty is the mean of continuous public reference, required-rollout
stationarity, and attractor-error components after successful integration. Catastrophic
integration receives the frozen failure penalty of 100.

## Common final evaluator

Every frozen endpoint is evaluated with the same deterministic public evaluator, irrespective of
search treatment. It reports:

- public contiguous-tail validation NRMSE and R-squared;
- short-ODE position trajectory NRMSE;
- complexity and actual variable dependence;
- 60-second DOP853 long-horizon integration at 3,000 output points;
- final 40% steady window, requiring at least three cycles;
- robust steady amplitude and detrended Hann-window dominant frequency;
- observed-validation, exact-zero, and discovery-scale large initial states;
- exact zero as `report_only`;
- observed-versus-large attractor consistency;
- structured integration and stability failures.

Frozen tolerances are amplitude 0.20, frequency 0.10, stationarity 0.15, attractor consistency
0.20, stationary amplitude fraction 0.001, state limit 1,000,000, relative integration tolerance
1e-8, and absolute tolerance 1e-10.

## Outcomes

The operational-gate primary outcomes are endpoint public validation NRMSE, endpoint continuous
long-horizon penalty, structured run success, and long-horizon overall pass. Secondary diagnostics
are amplitude/frequency errors, attractor consistency, short-trajectory NRMSE, complexity, actual
velocity dependence, wall time, requested evaluations, and LLM tokens.

Anytime AUC is not a confirmatory primary outcome in this gate. The current direct continuous PySR
runner exposes only an endpoint, while Hamilton exposes round boundaries. Requested-evaluation
boundary curves may be reported as exploratory diagnostics but cannot support an efficiency claim.

## Failure and stopping

- Failed, rejected, interrupted, replayed, and rolled-back search attempts consume their reserved
  requested evaluations and must remain in the ledger.
- A missing or invalid endpoint receives the common failure penalty and is never omitted.
- Hamilton runs all three rounds unless a deterministic execution failure prevents continuation.
- Scientific success cannot be declared from solver completion alone.
- This gate cannot authorize additional tasks, repeats, private/OOD access, or a formal study.

## Authorization boundary

The numerical ceilings in this protocol were explicitly authorized on 2026-08-12. This does not
override the launch gate: Julia/PySR preflight must pass within 180 seconds, and launching also
requires a newly generated bundle whose hashes bind the then-current Git commit, configs, public
data, environment, seeds, and persistent background-log command. Private/OOD remains forbidden.
