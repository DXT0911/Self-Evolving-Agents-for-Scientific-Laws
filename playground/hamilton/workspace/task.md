# VIV blind equation-family discovery

## Public scientific objective

Infer a family of autonomous second-order ordinary differential equations from
wind-tunnel vibration time series:

```text
x'' = f(x, x'; U)
```

Here `U` is wind speed. Discover the functional structure and its coefficients from the
provided training observations. Do not assume that a published benchmark structure is
correct, and do not use engineered features derived from a candidate answer.

The five operating conditions come from the same physical specimen at different wind
speeds. Whether they share equation structure is a hypothesis to test, not a supplied
answer.

## Agent-visible training data

| Wind speed | Discovery file |
|---|---|
| 2.48 m/s | `input/U248_train.csv` |
| 2.54 m/s | `input/U254_train.csv` |
| 2.60 m/s | `input/U260_train.csv` |
| 2.73 m/s | `input/U273_train.csv` |
| 2.82 m/s | `input/U282_train.csv` |

Each file has:

| Column | Meaning | Unit |
|---|---|---|
| `t` | time | s |
| `x` | displacement | mm |
| `v` | velocity | mm/s |
| `a` | acceleration | mm/s² |

The runner, not the LLM-facing editor, reads these files. Training files may be used for
discovery and contiguous internal validation. Sealed test and OOD data are not available
for search, model selection, or hyperparameter adaptation.

## Round-1 literature grounding

Before configuring symbolic regression, use `literature-grounding` to search broad
scholarly evidence about the phenomenon. Record cited qualitative priors in the
`EVO_INITIAL_PRIORS` block in `plan.md`.

Do not search for the dataset publication, a benchmark method, a reference equation, or
an answer term list. Do not convert literature statements into a prescribed equation or
PySR template.

## Neutral round-1 experiment baseline

This is a compute and evaluation baseline, not an equation baseline:

- use one training wind speed first: `U248_train.csv`;
- use raw variables `x` and `v` to predict `a`;
- use the complete file with a contiguous 20% validation tail;
- set `data.standardize_search=true`;
- use binary operators `+`, `-`, and `*`, with no unary operators;
- use deterministic serial PySR with random state 42;
- use `max_evals=8000`, `maxsize=31`, and `top_k=10`;
- enable candidate reranking with pointwise validation, short ODE behavior, and
  complexity;
- do not introduce a structural template in round 1.

All later rounds must change exactly one supported configuration field and state a
falsifiable reason for that intervention.

## Evidence and success rules

Treat the following as different outcomes:

1. solver completion;
2. internal pointwise improvement;
3. dynamically valid behavior under integration;
4. structure that remains defensible across operating conditions;
5. final generalization on sealed initial-condition and operating-condition tests.

Use the following evidence ladder without collapsing its levels:

- **Tier 0:** contiguous internal validation from the discovery record;
- **Tier 1:** the same operating condition with a sealed different initial condition;
- **Tier 2:** an excluded operating condition evaluated with one shared equation that
  explicitly uses the operating variable;
- **Tier 3:** one-shot final evaluation in sealed external regimes.

Tier 1 and Tier 2 aggregate summaries may be used for development only within their
controller access budgets. Tier 3 is final-only: once its controller attestation is
created, no further adaptive round is allowed. Record the frozen candidate ID and highest
completed tier, and do not declare the benchmark solved without a Tier 3 attestation.

For every promoted candidate, report:

- the original-unit equation;
- train and contiguous-validation metrics;
- short-ODE status and trajectory error;
- structured validation-residual state and temporal diagnostics;
- complexity and scientific score;
- scale-aware variable evidence;
- limitations and a falsifiable next step.

The reference equation family, coefficients, target amplitudes, test records, and OOD
labels are private benchmark assets. They must never be requested, inferred from file
paths, or written into `plan.md`, `findings.md`, `trace.md`, experiment configs, or
prompts.
