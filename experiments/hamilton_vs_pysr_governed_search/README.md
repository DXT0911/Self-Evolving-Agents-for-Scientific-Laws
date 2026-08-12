# Governed Hamilton versus fixed PySR

Chinese translation: [`README.zh-CN.md`](README.zh-CN.md).

This directory contains the preregistration and offline preparation for a controlled
comparison of the current governed Hamilton search controller with fixed PySR search.

## Current status

`public_operational_gate_completed`

The three-task, one-repeat public operational gate completed all nine arms. Hamilton ran
first, and the two baselines received its frozen realized budget trace. No private/OOD
asset was accessed. The result is a runtime pilot with mixed positive signals, not a
completed formal multi-repeat benchmark or proof of general superiority.

Read [`OPERATIONAL_GATE_STATUS_2026-07-28.md`](OPERATIONAL_GATE_STATUS_2026-07-28.md) for
the compact Chinese report. The `frozen_waiting_authorization` value preserved in
`arm_contracts.yaml` describes the pre-execution frozen contract; it is historical contract
metadata, not the current experiment status. The operational-gate authorization is spent
and does not authorize any further DeepSeek or PySR/Julia execution.

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
- `viv_long_horizon_replay.py`: replays the completed public U248 candidates through the
  deterministic Tier-0 long-horizon verifier without importing PySR or calling an LLM.
- `VIV_LONG_HORIZON_CALIBRATION_2026-08-12.md`: compact synthetic and historical-candidate
  calibration report; it is not preregistered evidence or launch authorization.
- `test_build_launch_bundle.py`, `test_prepare_public_data.py`,
  `test_validate_manifest.py`, `test_evaluation_curves.py`, and
  `test_ground_truth_equivalence.py`: offline contract tests.

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

## Required decisions before any further run

Any new repeat or expanded task set is a new execution decision. Before it starts:

1. Freeze the intended task/repeat scope and a new cumulative PySR evaluation budget.
2. Freeze the post-hoc AUC and equivalence definitions before observing new outcomes if
   they will be used as confirmatory metrics.
3. Separately authorize DeepSeek and PySR/Julia for that new scope.
4. Continue to prohibit private/OOD access unless a later Tier decision is independently
   authorized.

The preserved pairing rule remains Hamilton → freeze allowances and seeds → ordinary PySR
plus fixed-schedule PySR. The completed operational gate used a 12,000 ceiling per task and
the dynamic bounds recorded in the frozen manifest. Those spent allowances must not be
silently reused as authorization for future runs.

The ten external pilot inputs have been selected, downloaded at a pinned PMLB revision,
and fingerprinted in `pilot_manifest.yaml`. Their bytes remain in the Git-ignored
`data_cache/`; VIV U248 is referenced from the existing versioned public workspace input.

Private test/OOD data is outside the scope of this experiment.
