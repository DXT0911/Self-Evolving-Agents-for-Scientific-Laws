<!-- SRBENCH_ANCHOR_PROBLEM_STAGING -->
# SRBench Problem Staging

Put OpenEvolve symbolic regression problem packs here so they are symlinked into each Hamilton run workspace as `problems/`.

Recommended layout:

```text
playground/hamilton_srbench/problems/
  phys_osc/
    PO10/
      initial_program.py
      evaluator.py
      config.yaml
      X_train_for_eval.npy
      y_train_for_eval.npy
      problem_manifest.json
```

For benchmark integrity, prefer staging only training-visible assets here. Keep held-out test/OOD arrays outside the Hamilton workspace and run final evaluation separately.

Use `scripts/hamilton_srbench/stage_openevolve_problem.py` to prepare a staged copy from an OpenEvolve-generated problem directory.

Use `scripts/hamilton_srbench/export_real_openevolve_problem.py` to generate a real single-problem pack from OpenEvolve's `data_api.py` and the upstream LLM-SRBench dataset, then stage the Hamilton-visible subset here:

```bash
python scripts/hamilton_srbench/export_real_openevolve_problem.py \
  --split phys_osc \
  --problem PO10 \
  --openevolve-root /tmp/openevolve/examples/symbolic_regression
```

This creates a full official source pack under `/tmp/hamilton_srbench_exports/problems/<split>/<problem>/` and a Hamilton-visible staged pack under this directory. Held-out test/OOD arrays remain hidden unless `--include-hidden` is passed.

The helper first tries the upstream dataset repo `nnheui/llm-srbench`. If that repo is gated in the current environment, it falls back to `pkuHaowei/llm-srbench`.
