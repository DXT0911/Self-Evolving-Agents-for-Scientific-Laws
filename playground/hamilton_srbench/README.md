<!-- SRBENCH_ANCHOR_ONE_CLICK_RUN -->
# Hamilton SRBench Reproduction Notes

This directory holds the Hamilton vs OpenEvolve symbolic regression benchmark setup used for the synchronized `PO10` comparison.

## Scope

- Problem family: `phys_osc/PO10`
- Hamilton-visible staged pack: `playground/hamilton_srbench/problems/phys_osc/PO10`
- Full held-out pack: `playground/hamilton_srbench/full_problems/phys_osc/PO10`
- Latest committed 5-round Hamilton run: `runs/hamilton_20260317_133242`
- Latest shared comparison JSON: `playground/hamilton_srbench/openevolve_runs_layoutfix/phys_osc/PO10/compare_hamilton_sync5_vs_openevolve.json`

## Environment

Use the repo-local virtualenv and provide the model endpoint variables before running any command:

```bash
cd /home/zychen/SRAgent/Self-Evolving-Agents-for-Scientific-Laws
export OPENAI_API_KEY='YOUR_KEY'
export GPT_BASE_URL='https://llm.dp.tech'
export GPT_CHAT_MODEL='gpt-5-chat'
```

## One-Click Hamilton Run

This reproduces the formal 5-round Hamilton search on the synchronized visible pack and writes a new run under `runs/`.

```bash
cd /home/zychen/SRAgent/Self-Evolving-Agents-for-Scientific-Laws
OPENAI_API_KEY="$OPENAI_API_KEY" \
GPT_BASE_URL="$GPT_BASE_URL" \
GPT_CHAT_MODEL="$GPT_CHAT_MODEL" \
./.venv/bin/python run.py \
  --agent hamilton \
  --config configs/hamilton_srbench/config.yaml \
  --task "Solve problems/phys_osc/PO10 with a formal 5-round Hamilton search. This is not a smoke test. In round 1 you must actually use PySR. In every round generate at least three candidate program files under history/roundN/scripts, rank them with ./scripts/hamilton_srbench/select_best_candidate.py on problems/phys_osc/PO10, promote only the best to candidate_model.py, and record the ranking plus rationale in plan.md and findings.md. Return task_completed='false' in rounds 1-4. In round 5, after recording the final best candidate and next-step conclusions, you may return task_completed='true'."
```

## One-Click OpenEvolve Run

This reproduces the OpenEvolve baseline on the full pack.

```bash
cd /home/zychen/SRAgent/Self-Evolving-Agents-for-Scientific-Laws
OPENAI_API_KEY="$OPENAI_API_KEY" \
./.venv/bin/python scripts/hamilton_srbench/run_openevolve_problem.py \
  --problem-dir playground/hamilton_srbench/full_problems/phys_osc/PO10 \
  --primary-model "$GPT_CHAT_MODEL" \
  --secondary-model "$GPT_CHAT_MODEL" \
  --api-base "$GPT_BASE_URL" \
  --iterations 50 \
  --output-dir playground/hamilton_srbench/openevolve_runs_layoutfix/phys_osc/PO10
```

## One-Click Shared Comparison

This evaluates the Hamilton final candidate, the OpenEvolve final program, and the provided baseline with the same deterministic post-evaluator.

```bash
cd /home/zychen/SRAgent/Self-Evolving-Agents-for-Scientific-Laws
./.venv/bin/python scripts/hamilton_srbench/compare_methods.py \
  --problem-dir playground/hamilton_srbench/full_problems/phys_osc/PO10 \
  --hamilton-program runs/hamilton_20260317_133242/workspaces/task_0/candidate_model.py \
  --openevolve-program playground/hamilton_srbench/openevolve_runs_layoutfix/phys_osc/PO10/openevolve_output/best/best_program.py \
  --baseline-program playground/hamilton_srbench/full_problems/phys_osc/PO10/initial_program.py \
  --restarts 4 \
  --seed 0 \
  --output playground/hamilton_srbench/openevolve_runs_layoutfix/phys_osc/PO10/compare_hamilton_sync5_vs_openevolve.json
```

## Audit Artifacts

For review, inspect:

- `runs/hamilton_20260317_133242/workspaces/task_0/task.md`
- `runs/hamilton_20260317_133242/workspaces/task_0/plan.md`
- `runs/hamilton_20260317_133242/workspaces/task_0/findings.md`
- `runs/hamilton_20260317_133242/workspaces/task_0/history/round*/scripts/`
- `runs/hamilton_20260317_133242/workspaces/task_0/history/round*/results/selection.json`
- `runs/hamilton_20260317_133242/trajectories/task_0/trajectory.json`
