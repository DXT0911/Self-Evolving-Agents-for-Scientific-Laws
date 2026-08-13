# Dataset selection and acquisition plan

Chinese translation: [`DATASETS.zh-CN.md`](DATASETS.zh-CN.md).

## Selection principles

The benchmark must separate search-control ability from VIV-specific identifiability.
Tasks are included only when they:

- are public and have a traceable source and license;
- can be represented by the current scalar symbolic-regression runner, or by a small
  preregistered adapter;
- permit the same features, target, split, search space, and evaluator for all arms;
- do not require private/OOD access;
- have enough rows for a discovery/validation split;
- do not expose a ground-truth equation to the Agent.

Tasks are excluded when they require PDE discovery, image/text inputs, unbounded categorical
processing, missing target definitions, or a major new multi-equation controller during
the pilot.

## Family A: blind static known-truth tasks

Source candidates:

- AI-Feynman Symbolic Regression Database:
  `https://space.mit.edu/home/tegmark/aifeynman.html`
- standardized PMLB/SRBench versions:
  `https://github.com/EpistasisLab/pmlb`
  and `https://github.com/cavalab/srbench`

The six pilot identifiers are frozen at PMLB revision
`7c1f4bdc00136dc2e55c87fa6b8ba6e8af6d1a68`:

| Opaque task | PMLB source ID | Structural slot |
|---|---|---|
| `static_s01` | `feynman_I_14_4` | polynomial interaction |
| `static_s02` | `feynman_I_12_2` | rational multivariable |
| `static_s03` | `feynman_II_15_4` | periodic/trigonometric |
| `static_s04` | `feynman_I_6_2a` | exponential |
| `static_s05` | `feynman_I_18_4` | mixed rational |
| `static_s06` | `feynman_III_9_52` | difficult mixed periodic/rational |

These identifiers were selected before any Hamilton/PySR pilot outcome. Dataset bytes were
downloaded from the pinned Git LFS revision into the ignored `data_cache/`; their sizes and
SHA-256 fingerprints are frozen in `pilot_manifest.yaml`. Row counts, feature mappings, and
the public split adapter still require validation. A deterministic nuisance-variable
transformation may be added only as a separately versioned task; it will not silently
replace one of these six inputs.

To reduce LLM memorization leakage:

- task IDs and variables presented to the Agent are opaque;
- equation names and physics chapter labels are removed;
- reference expressions remain controller-side;
- the primary blind track supplies no formula-specific literature context.

## Family B: known-truth dynamical derivatives

Primary source candidate:

- ODE-Strogatz: `https://github.com/lacava/ode-strogatz`

The public source provides two-state nonlinear ODE systems as separate regression tasks for
each derivative. The four pilot identifiers are frozen at the same PMLB revision:

| Opaque task | PMLB source ID | Structural challenge |
|---|---|---|
| `dynamic_d01` | `strogatz_vdp1` | cubic nonlinear interaction |
| `dynamic_d02` | `strogatz_barmag1` | coupled trigonometric terms |
| `dynamic_d03` | `strogatz_glider2` | division and trigonometric term |
| `dynamic_d04` | `strogatz_shearflow2` | mixed trigonometric products |

Each task discovers one derivative from two state variables. This is compatible with the
current scalar regression runner when ODE rollout is disabled. It tests symbolic recovery
on dynamical data, but it does not by itself test joint trajectory or attractor recovery.
The pilot does not introduce joint multi-equation discovery; that remains a separate future
experiment.

## Family C: public VIV

Pilot task:

```text
playground/hamilton/workspace/input/U248_train.csv
```

Expansion candidates:

- `U254_train.csv`
- `U260_train.csv`
- `U273_train.csv`
- `U282_train.csv`

Only the public training files are eligible. The existing contiguous-tail validation rule
is retained. Private paired-initial-condition, held-out test, and external-regime files are
not part of acquisition or analysis.

The five wind speeds form one correlated VIV family. They must not be counted as five
independent benchmark domains.

## Acquisition state

The ten external inputs are locally acquired from PMLB revision
`7c1f4bdc00136dc2e55c87fa6b8ba6e8af6d1a68`. The cache is intentionally ignored by Git;
the committed manifest is the integrity lock. VIV U248 is already a versioned public input.

Before launch, adapter preparation must still:

1. verify gzip integrity, row counts, finite numeric columns, and target mappings;
2. create deterministic public train/validation splits;
3. generate opaque Agent-facing metadata;
4. keep reference equations outside run workspaces;
5. validate that no path or manifest entry refers to private/OOD assets.
