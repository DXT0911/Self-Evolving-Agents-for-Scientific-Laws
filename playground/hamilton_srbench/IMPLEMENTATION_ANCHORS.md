<!-- SRBENCH_ANCHOR_IMPLEMENTATION_DOC -->
# Hamilton SRBench Implementation Anchors

This document records the minimum integration scheme for running OpenEvolve symbolic regression problems with the existing Hamilton loop.

## Overall Scheme

1. Keep Hamilton's existing single-agent, multi-round HCC loop.
2. Replace the VIV-specific workspace template and prompt set with SRBench-specific ones.
3. Stage each OpenEvolve problem as a read-only problem pack under `playground/hamilton_srbench/problems/`.
4. Require Hamilton to maintain a workspace-root `candidate_model.py` that matches OpenEvolve's evaluator contract.
5. Use the provided `evaluator.py` during each round for local scoring; reserve held-out test/OOD evaluation for external post-run checks.

## Anchor Index

| Anchor | File | Purpose |
|--------|------|---------|
| `SRBENCH_ANCHOR_CORE_TEMPLATE_DIR` | `playground/hamilton/core/playground.py` | Workspace template directory is configurable |
| `SRBENCH_ANCHOR_CORE_INPUT_POLICY` | `playground/hamilton/core/playground.py` | `input/*.csv` validation is configurable |
| `SRBENCH_ANCHOR_CFG_MAIN` | `configs/hamilton_srbench/config.yaml` | SRBench-specific Hamilton config |
| `SRBENCH_ANCHOR_TASK_TEMPLATE` | `playground/hamilton_srbench/workspace/task.md` | SRBench task contract in workspace |
| `SRBENCH_ANCHOR_PROBLEM_STAGING` | `playground/hamilton_srbench/problems/README.md` | Problem pack layout and staging rule |
| `SRBENCH_ANCHOR_STAGE_SCRIPT` | `scripts/hamilton_srbench/stage_openevolve_problem.py` | Helper script for staging OpenEvolve problems |
| `SRBENCH_ANCHOR_STAGE_HASH_AUDIT` | `scripts/hamilton_srbench/stage_openevolve_problem.py` | Record file hashes and pack fingerprints in staged manifests so visible/full snapshot mismatches are auditable |
| `SRBENCH_ANCHOR_REAL_EXPORT_SCRIPT` | `scripts/hamilton_srbench/export_real_openevolve_problem.py` | Export one official problem from OpenEvolve/LLM-SRBench and stage it |
| `SRBENCH_ANCHOR_SYNC_EXPORT` | `scripts/hamilton_srbench/export_real_openevolve_problem.py` | Stage both visible and full packs from one generated source snapshot |
| `SRBENCH_ANCHOR_LOCAL_CODEGEN` | `scripts/hamilton_srbench/openevolve_codegen_fallback.py` | Local fallback generator for OpenEvolve-style problem packs when `/tmp/openevolve` is unavailable |
| `SRBENCH_ANCHOR_RUNTIME_PYTHON` | `configs/hamilton_srbench/config.yaml` | Symlink the repo `.venv` into each workspace so evaluator runs can use `./.venv/bin/python` |
| `SRBENCH_ANCHOR_SKILL_SCOPE` | `configs/hamilton_srbench/config.yaml` | Limit SRBench skill loading to `pysr` to avoid `evo-protocol` detours |
| `SRBENCH_ANCHOR_SMOKE_FINISH` | `playground/hamilton_srbench/workspace/task.md` | Force smoke tests to stop immediately after a successful evaluator run and write-back |
| `SRBENCH_ANCHOR_PYSR_PREFERENCE` | `playground/hamilton_srbench/workspace/task.md` | Prefer PySR-guided search on non-trivial SRBench problems and require justification when skipped |
| `SRBENCH_ANCHOR_AUDIT_RECORDS` | `playground/hamilton_srbench/workspace/task.md` | Make `task.md`, `plan.md`, and `findings.md` mandatory audit artifacts for each SRBench run |
| `SRBENCH_ANCHOR_FINDINGS_APPEND` | `playground/hamilton/core/playground.py` and `playground/hamilton_srbench/workspace/task.md` | Seed and require a stable append marker for `findings.md` updates, avoiding fragile EOF line inserts |
| `SRBENCH_ANCHOR_POST_EVAL` | `scripts/hamilton_srbench/post_eval_candidate.py` | Shared deterministic post-evaluation for final Hamilton/OpenEvolve program comparison |
| `SRBENCH_ANCHOR_COMPARE_METHODS` | `scripts/hamilton_srbench/compare_methods.py` | One-command Hamilton vs OpenEvolve comparison on the same full problem pack |
| `SRBENCH_ANCHOR_FULL_PACK_POLICY` | `playground/hamilton_srbench/full_problems/README.md` | Keep held-out full packs separate from Hamilton-visible train-only staged packs |
| `SRBENCH_ANCHOR_OPENEVOLVE_RUNNER` | `scripts/hamilton_srbench/run_openevolve_problem.py` | Prepare or run OpenEvolve on a full SRBench problem pack with normalized workdir/output paths |
| `SRBENCH_ANCHOR_SELECT_BEST` | `scripts/hamilton_srbench/select_best_candidate.py` | Deterministically rank multiple Hamilton candidates on the same visible SRBench problem pack and promote the best one |
| `SRBENCH_ANCHOR_ONE_CLICK_RUN` | `playground/hamilton_srbench/README.md` | One-click reproduction commands for Hamilton, OpenEvolve, and the shared post-evaluation |

## Expected Run Command

```bash
python run.py \
  --agent hamilton \
  --config configs/hamilton_srbench/config.yaml \
  --task "Solve problems/phys_osc/PO10. Read initial_program.py and evaluator.py, improve candidate_model.py, and evaluate each round."
```

## Real Problem Export Command

```bash
python scripts/hamilton_srbench/export_real_openevolve_problem.py \
  --split phys_osc \
  --problem PO10 \
  --openevolve-root /tmp/openevolve/examples/symbolic_regression
```

The export helper first tries the upstream dataset repo `nnheui/llm-srbench`. If that repo is gated in the current environment, it falls back to `pkuHaowei/llm-srbench`.

## Static Contract Checklist

- `playground/hamilton_srbench/problems/` is mounted into the workspace as `problems/`
- `candidate_model.py` lives in the workspace root
- `plan.md` and `findings.md` hold the persistent best-score memory
- `history/roundN/scripts/` and `history/roundN/results/` hold per-round artifacts
- Final hidden-set evaluation should be run outside Hamilton when benchmark integrity matters
