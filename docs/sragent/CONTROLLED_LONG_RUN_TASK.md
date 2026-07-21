# Hamilton controlled long-run benchmark

Test whether a general adaptive SR agent can improve a discovered dynamical law over at
most eight evidence-driven rounds. U248 is a benchmark, not a hard-coded Hamilton design.

## Data and privacy

- Use only `input/U248_train.csv` through `run-sr-experiment`.
- Never view, print, copy, summarize manually, or send raw CSV rows to the LLM.
- Do not read test or OOD data.
- Use raw discovery variables `x,v` and target `a`; do not engineer known equation terms.
- Use the complete training file with a contiguous 20% validation tail.

## Round 1 baseline

Use exactly:

- `max_rows=null`, `search_stride=5`, `validation_fraction=0.2`;
- binary operators `+,-,*`, unary operators `square,cube`;
- `niterations=500`, `max_evals=12000`;
- `populations=8`, `population_size=32`, `tournament_selection_n=12`;
- `maxsize=31`, `parsimony=0.001`, `random_state=42`, `top_k=10`;
- candidate ranking weights: validation NRMSE 1.0, trajectory NRMSE 1.0,
  complexity 0.05, failure penalty 100;
- short ODE: 10 seconds, 1000 points, state limit 1000000.

Write the result under `history/round1/results/`.

## Adaptive rounds

For round N > 1:

1. Read only L2 and the preceding result evidence already summarized there.
2. Test one causal hypothesis by changing exactly one leaf configuration field.
3. `next_strategy.config_field` must contain exactly one path, such as
   `search.parsimony`; never list several paths.
4. Keep every other data, search, verification, seed, and ranking field unchanged.
5. Do not use a seed change as the main adaptation.
6. Respect the controller's total limit of 100000 PySR evaluations.
7. Record risks and a result that would falsify the hypothesis.

Do not assume that more iterations, more operators, or lower parsimony is beneficial.
Choose the next intervention from observed candidate structure, validation behavior,
rollout behavior, scale-aware diagnostics, and prior failed interventions.

Resume exception: if round 2 starts from a preserved round-1 result after an interrupted
Promotion phase and `EVO_NEXT_ROUND` is absent, change only
`search.binary_operators` from `["+", "-", "*"]` to `["+", "-", "*", "/"]`.
Record division singularity/domain risks. This exception applies only to resumed round 2.

## Promotion gates

A later result may replace the incumbent only if:

- its scientific score is strictly lower;
- pointwise predictions and rollout are finite;
- ODE verification is completed and bounded;
- the improvement is not obtained by test/OOD leakage.

The first result may initialize a provisional incumbent even when scientifically weak.

## Scientific success criteria

Use `task_completed=true` only if the incumbent simultaneously has:

- both `x` and `v` dependence;
- at least one nonlinear term;
- validation R2 at least 0.65;
- scientific score below 0.70;
- completed, bounded 10-second-or-longer rollout;
- explicit evidence that success is not merely solver completion.

Otherwise return `task_completed=false`, preserve the best incumbent, and propose one
falsifiable next intervention. Reaching the maximum round count is not success.

## Required records

Every round must update `trace.md`, `findings.md`, and `plan.md`, including a valid
`EVO_SCIENTIFIC_DECISION` block and, when continuing, a valid `EVO_NEXT_ROUND` block.
Keep L2 compact: retain a per-round metric table, incumbent history, rejected hypotheses,
and the single next intervention. Do not paste full result JSON or raw data into L2.
