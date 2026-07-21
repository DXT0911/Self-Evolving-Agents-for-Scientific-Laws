# SR Agent Research Protocol

[English](./RESEARCH_PROTOCOL.md) | [简体中文](./RESEARCH_PROTOCOL.zh-CN.md)

## Scope

The research target is a general SR Agent that can:

1. inspect data and task metadata;
2. configure a symbolic-regression search;
3. execute a numerical SR engine;
4. evaluate candidates with task-specific verifiers;
5. diagnose failures and update the next search;
6. preserve reusable strategies across rounds and tasks.

VIV is the current deep validation case, not the definition of the general framework.
Synthetic systems and standard benchmarks should later provide breadth.

## Current two-week focus

Primary question:

> Does dynamics-aware verifier feedback help an SR Agent select equations that reproduce
> long-term nonlinear dynamics better than fit-only feedback?

Initial comparison:

1. direct PySR;
2. Hamilton with fit-only feedback;
3. Hamilton with fit and trajectory feedback;
4. optional Hamilton with term-level ablation feedback.

## VIV data protocol

The public Agent workspace contains training inputs only:

`playground/hamilton/workspace/input/`

Public training files:

- `U248_train.csv`
- `U254_train.csv`
- `U260_train.csv`
- `U273_train.csv`
- `U282_train.csv`

Controller-private benchmark assets live outside the Agent workspace under the ignored
directory `playground/hamilton/benchmarks/viv/private/`. They must never be copied into a
run workspace or committed. The private manifest records their roles and integrity
metadata.

Held-out testing (controller-private):

- `U248_test.csv`
- `U254_test.csv`
- `U260_test.csv`
- `U273_test.csv`
- `U282_test.csv`

Final OOD evaluation only (controller-private):

- `U000_free_vibration.csv`
- `U216_below_lockin.csv`
- `U300_above_lockin.csv`

Do not use test or OOD results to select operators, templates, complexity limits,
hyperparameters, prompts, or candidate equations.

The controller may release only the tier-appropriate compact summary defined by the OOD
protocol. Raw private rows, filenames beyond the approved manifest view, target labels,
and reference equations are never released to the Agent.

For internal validation, split training trajectories by contiguous time blocks. Do not use
random row splits because neighboring time samples are strongly correlated.

## Required evaluator outputs

Every candidate equation should produce a machine-readable record containing:

- equation and simplified equation;
- term list and complexity;
- training and internal-validation pointwise metrics;
- integration success/failure and failure reason;
- steady-state amplitude error;
- oscillation-frequency error;
- zero-to-stable qualitative behavior;
- big-to-stable qualitative behavior;
- agreement between attractors from both initial conditions;
- cross-speed structural consistency;
- runtime, search evaluations, random seed, model name and Git commit.

## Experiment artifact policy

Commit:

- source code;
- small configuration files;
- compact result summaries in JSON/CSV;
- final figures used in reports;
- environment/version manifests;
- documentation and experiment protocols.

Keep local or in external artifact storage:

- complete run workspaces;
- full trajectories and verbose LLM logs;
- PySR/Julia caches;
- repeated data copies;
- temporary plots;
- large candidate tables.

Each reported experiment must be reproducible from:

```text
Git commit
+ config
+ data version
+ random seed
+ environment versions
+ model/provider identifier
```

## Commit convention

Examples:

```text
docs(sragent): document VIV data and evaluation protocol
test(sragent): add evaluator smoke tests
feat(sragent): add dynamics-aware trajectory verifier
exp(sragent): add direct PySR VIV baseline
exp(sragent): compare fit-only and dynamics-aware feedback
fix(sragent): prevent test trajectory leakage
```

Update `playground/hamilton/TODO.md` whenever implementation status changes.
