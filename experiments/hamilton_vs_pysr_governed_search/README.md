# Governed Hamilton versus fixed PySR

This directory contains the preregistration and offline preparation for a controlled
comparison of the current governed Hamilton search controller with fixed PySR search.

## Current status

`frozen_waiting_authorization`

The task specs, initial numerical search configuration, seed plan, Hamilton dynamic-budget
bounds, and cumulative ceiling are frozen. Hamilton runs first. Only after its evaluation
ledger is frozen are the paired ordinary- and fixed-schedule-PySR configurations
materialized with exactly the same realized budget. Execution remains hard-disabled until
the user gives separate DeepSeek and PySR/Julia authorizations.

The comparison is not an old-Hamilton ablation. Its primary question is:

> Under the same public data, initial PySR search space, cumulative evaluation budget,
> candidate evaluator, and paired seed plan, does governed LLM search control outperform
> fixed PySR in validation quality, repeatability, and evaluation efficiency?

## Files

- `PROTOCOL.md`: hypotheses, experimental arms, fairness rules, metrics, and analysis plan.
- `DATASETS.md`: benchmark families, inclusion rules, isolation policy, and acquisition plan.
- `pilot_manifest.yaml`: machine-readable preparation state and planned pilot design.
- `arm_contracts.yaml`: frozen authority boundaries and allowed differences between arms.
- `result_record.schema.json`: compact per-repeat result contract.
- `prepare_public_data.py`: hash-checking adapter that creates opaque public CSV inputs.
- `task_specs.yaml`: frozen task adapters and shared initial numerical search space.
- `build_launch_bundle.py`: materializes the ignored 99-job launch bundle without execution.
- `freeze_paired_budget.py`: freezes one Hamilton ledger and generates its two paired
  PySR replay configurations without copying scientific outputs.
- `validate_launch_bundle.py`: audits all runner configurations and task data offline.
- `validate_manifest.py`: offline preparation/launch-readiness validator.
- `evaluation_curves.py`: reconstructs completed episode-boundary evaluation curves and
  computes a budget-weighted anytime AUC when at least two boundaries are observable.
- `controller_ground_truth.yaml`: controller-only reference equations and deterministic
  challenge-grid definitions; this file must never enter an Agent workspace.
- `ground_truth_equivalence.py`: checks algebraic, numerical, and variable-selection
  equivalence against the controller-only registry.
- `collect_ground_truth_equivalence.py`: applies the controller-only equivalence checks to
  every completed public result boundary in the launch bundle.

## Offline evaluation utilities

These commands neither import nor invoke PySR, Julia, or an LLM, and they do not access
private/OOD data:

```bash
python -m experiments.hamilton_vs_pysr_governed_search.evaluation_curves
python -m experiments.hamilton_vs_pysr_governed_search.ground_truth_equivalence \
  static_s01 --result path/to/result.json
python -m experiments.hamilton_vs_pysr_governed_search.collect_ground_truth_equivalence
```

The curve utility uses cumulative *requested* evaluations and completed round/episode
boundaries because the legacy pilot did not record engine-measured per-evaluation
timestamps. A one-shot ordinary PySR result receives a `null` anytime AUC: one terminal
value is not presented as an anytime trajectory. The equivalence utility keeps algebraic
and strict controller-only challenge-grid decisions separate. VIV is explicitly marked
not applicable because it has no unique registered ground-truth equation.

For the already completed pilot these definitions are post-hoc exploratory diagnostics:
the interpolation rule, challenge grid, and tolerances were added after outcomes existed.
They must be frozen before any later repeat if they are to support confirmatory claims.
- `test_build_launch_bundle.py`, `test_prepare_public_data.py`,
  `test_validate_manifest.py`: offline contract tests.

## Offline validation

This command only parses local YAML and performs static checks:

```powershell
python -m unittest experiments.hamilton_vs_pysr_governed_search.test_validate_manifest
python -m unittest experiments.hamilton_vs_pysr_governed_search.test_prepare_public_data
python -m unittest experiments.hamilton_vs_pysr_governed_search.test_build_launch_bundle
python experiments/hamilton_vs_pysr_governed_search/build_launch_bundle.py
python experiments/hamilton_vs_pysr_governed_search/validate_launch_bundle.py
python experiments/hamilton_vs_pysr_governed_search/validate_manifest.py `
  experiments/hamilton_vs_pysr_governed_search/pilot_manifest.yaml `
  --mode preparation
```

Launch readiness is expected to fail during preparation:

```powershell
python experiments/hamilton_vs_pysr_governed_search/validate_manifest.py `
  experiments/hamilton_vs_pysr_governed_search/pilot_manifest.yaml `
  --mode launch
```

That failure is a safety property, not an experiment failure.

After the ignored public source cache is present, opaque inputs can be reproduced without
an LLM, PySR, or Julia:

```powershell
python -m experiments.hamilton_vs_pysr_governed_search.prepare_public_data `
  experiments/hamilton_vs_pysr_governed_search/pilot_manifest.yaml
```

## Required decisions before any run

The remaining launch gates are:

1. Authorize the frozen cumulative PySR evaluation budget together with PySR/Julia use.
2. Separately authorize DeepSeek use under the frozen Hamilton token ceilings.
3. After both approvals, run the 9-job public operational gate before the remaining pilot.

Within each task/repeat, execution order is Hamilton → freeze allowances and seeds →
ordinary PySR plus fixed-schedule PySR. Hamilton has a 12,000 ceiling with dynamic bounds
`min=2,000`, `base=4,000`, and `max=6,000`; both baselines receive only its realized
evaluations.

The ten external pilot inputs have been selected, downloaded at a pinned PMLB revision,
and fingerprinted in `pilot_manifest.yaml`. Their bytes remain in the Git-ignored
`data_cache/`; VIV U248 is referenced from the existing versioned public workspace input.

Private test/OOD data is outside the scope of this experiment.
