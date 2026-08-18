#!/usr/bin/env python3
"""Materialize the frozen HCC hybrid pilot (3 seed × 2 task × 2 arms) without running it.

Does not import or invoke PySR, Julia, or an LLM API.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
V1 = HERE.parent / "hamilton_vs_pysr_governed_search"
OUTPUT = HERE / "run_bundle"
HCC_CONFIG = REPO / "configs/hamilton/config_hcc_hybrid_pilot.yaml"
BASELINE_EXEC = HERE / "execute_baseline.py"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from experiments.hamilton_vs_pysr_governed_search.build_launch_bundle import (
    materialize_input,
    runner_config,
    sha256,
    task_context,
    write_json,
    write_text,
)


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a mapping")
    return value


def rel(path: Path) -> str:
    return path.resolve().relative_to(REPO.resolve()).as_posix()


def frozen_search(manifest: dict[str, Any]) -> dict[str, Any]:
    f = manifest["frozen_round1"]
    return {
        "engine": f["engine"],
        "binary_operators": list(f["binary_operators"]),
        "unary_operators": list(f["unary_operators"]),
        "niterations": int(f["niterations"]),
        "populations": int(f["populations"]),
        "population_size": int(f["population_size"]),
        "tournament_selection_n": int(f["tournament_selection_n"]),
        "maxsize": int(f["maxsize"]),
        "parsimony": float(f["parsimony"]),
        "top_k": int(f["top_k"]),
    }


def task_context_cn(task: dict[str, Any]) -> str:
    features = ", ".join(task["feature_columns"])
    if task["context"] == "blind_dynamic_derivative":
        return (
            f"特征列（{features}）是状态变量，y 是其中一个状态的导数；t 仅保留源行顺序，"
            "不是物理时间 rollout 的证据。"
        )
    return (
        f"特征列（{features}）是不透明预测变量，y 是目标；t 是确定性排序索引，不是科学输入。"
    )


def frozen_round1_block(task: dict[str, Any], search: dict[str, Any], per_round: int) -> dict[str, Any]:
    # Mirror runner_config()'s verification block exactly so arm H's frozen round-1
    # config is symmetric with arm B. The runner reads verification.short_ode (and
    # candidate_ranking) unconditionally at execution, so they must be present.
    ranking = task.get("_candidate_ranking")
    verification: dict[str, Any] = {
        "short_ode": task["short_ode"],
        "residual_diagnostics": {
            "enabled": True,
            "max_lag": 50,
            "feature_bins": 4,
            "phase_bins": 8,
            "high_frequency_fraction": 0.25,
        },
    }
    if ranking:
        verification["candidate_ranking"] = ranking
    return {
        "data": {
            "time_column": task["time_column"],
            "feature_columns": list(task["feature_columns"]),
            "target_column": task["target_column"],
            "validation_fraction": task["validation_fraction"],
            "search_stride": task["search_stride"],
            "standardize_search": task["standardize_search"],
        },
        "search": {**search, "max_evals": per_round},
        "verification": verification,
    }


def hcc_task_md(
    task_id: str,
    task: dict[str, Any],
    search: dict[str, Any],
    repeat_id: str,
    rounds: int,
    total_evals: int,
    per_round: int,
) -> str:
    block = json.dumps(frozen_round1_block(task, search, per_round), indent=2, ensure_ascii=False)
    return f"""# 冻结符号回归任务（HCC 混合线路 pilot）

任务标识：`{task_id}`（重复 `{repeat_id}`，seed 由 controller 注入，LLM 不得自行设置 random_state）。

{task_context_cn(task)}

只用 `input/data.csv` 通过 run-sr-experiment 技能跑 PySR；不要直接读原始行、不要定位隐藏真值/私有/OOD 数据、不要用文献搜索。共 {rounds} 轮 Discovery，累计 PySR 评估上限 {total_evals}（每轮 {per_round}，由 controller 确定性分配，LLM 不拥有 search.max_evals）。

## 第 1 轮（必须精确使用以下配置）

```json
{block}
```

round 1 的 `data`、`search`、`verification` 必须与上面 JSON **逐字段完全一致**（照抄，不要增删改）。`search.random_state` 由 controller 注入，不要写 `random_state` 字段。`verification` 里的 `short_ode`、`candidate_ranking`、`residual_diagnostics` 全部照抄；尤其 `candidate_ranking.weights.trajectory_nrmse` 必须为 0.0、`short_ode.enabled` 必须为 false、`residual_diagnostics.enabled` 必须为 true 且跨轮固定。

## 第 2/3 轮

第 2/3 轮均为**独立冷启动** PySR 搜索，不继承任何上一轮进化种群，每轮完整运行 1500 evals，保留历史最优 incumbent。

每轮在 plan.md 的 `EVO_SCIENTIFIC_DECISION` 块里写 `next_strategy`，`action` 只允许 `"modify"` 或 `"continue"` 两种，禁止 `"restart"`，禁止改 controller-owned 的 `search.max_evals`：

- `action: "modify"`（推荐，默认）：`config_field` 必须是带点号的 `search.*` 路径，`config_patch` 必须恰好是这一个字段的映射。示例：`"config_field": "search.parsimony", "config_patch": {{"search.parsimony": 0.0005}}`。可改字段（每轮只能改一个）：`search.parsimony`、`search.niterations`、`search.populations`、`search.population_size`、`search.tournament_selection_n`、`search.top_k`、`search.maxsize`、`search.unary_operators`、`search.binary_operators`。
- `action: "continue"`（仅当你判断无需任何改动时）：必须 `"config_field": null` 且 `"config_patch": {{}}`。

无论哪种 action，都必须完整填写 `diagnosed_failure`、`evidence`、`expected_effect`、`alternative_explanation`、`expected_residual_change`、`falsification`、`risks`（非空列表）、`residual_evidence`（含 result_file / finding / observed），并更新 findings.md / plan.md。不要提前结束整个三轮实验。
"""


def build(output: Path = OUTPUT) -> dict[str, Any]:
    manifest = load_yaml(HERE / "pilot_manifest.yaml")
    specs = load_yaml(V1 / "task_specs.yaml")
    if manifest["status"] != "frozen_pre_execution":
        raise ValueError("manifest is not frozen")
    tasks = list(manifest["tasks"])
    seeds = list(manifest["seeds"])
    rounds = int(manifest["rounds"])
    per_round = int(manifest["requested_evaluations_per_round"])
    per_run = int(manifest["requested_evaluations_per_run"])
    if per_round * rounds != per_run:
        raise ValueError("per-round and per-run evaluation authorization do not reconcile")
    search = frozen_search(manifest)

    jobs: list[dict[str, Any]] = []
    for task_id in tasks:
        task = dict(specs["tasks"][task_id])
        task["_candidate_ranking"] = task.get(
            "candidate_ranking_override", specs["shared_verification"]["candidate_ranking"]
        )
        source = (V1 / task["input"]).resolve()
        if not source.is_file() or sha256(source) != task["input_sha256"]:
            raise ValueError(f"missing or changed frozen input: {source}")

        for index, seed in enumerate(seeds):
            repeat = f"repeat_{index + 1}"
            seed_plan = {
                "schema_version": 1,
                "task_id": task_id,
                "repeat_id": repeat,
                "round_seeds": [seed] * rounds,
                "controller_owned": True,
            }

            # Arm H (free-LLM HCC loop). Workspace is <root>/workspaces/task_0.
            h_root = output / "hcc_llm" / task_id / repeat
            h_ws = h_root / "workspaces" / "task_0"
            materialize_input(source, h_ws / "input/data.csv", task["input_sha256"])
            write_text(h_ws / "task.md", hcc_task_md(task_id, task, search, repeat, rounds, per_run, per_round))
            write_json(h_ws / ".hamilton_seed_plan.json", seed_plan)
            write_json(h_ws / ".hamilton_bridge_policy.json", {
                "schema_version": 1,
                "restart_rounds": [3],
                "restart_cost_evals": per_round,
            })
            jobs.append({
                "arm": "hcc_llm",
                "task_id": task_id,
                "repeat_id": repeat,
                "seed": seed,
                "root": rel(h_root),
                "workspace": rel(h_ws),
                "state": "ready_waiting_runtime_authorizations",
                "commands": [[
                    "python", rel(REPO / "run.py"), "--agent", "hamilton",
                    "--config", rel(HCC_CONFIG),
                    "--task", f"Execute frozen HCC hybrid task {task_id}, {repeat}.",
                    "--run-dir", rel(h_root),
                ]],
                "requires": ["deepseek_authorization", "pysr_julia_authorization"],
            })

            # Arm B (bare persistent warm PySR, no LLM). Workspace is <root>/workspace.
            b_root = output / "bare_pysr" / task_id / repeat
            b_ws = b_root / "workspace"
            materialize_input(source, b_ws / "input/data.csv", task["input_sha256"])
            baseline = runner_config(
                task_id,
                task,
                search,
                per_round,
                seed,
                f"hcc_bare__{task_id}__{repeat}__round1",
                "history/round1/results/result.json",
            )
            baseline["output"]["run_directory"] = "session/pysr"
            write_json(b_ws / "round1_baseline.json", baseline)
            write_json(b_ws / ".hamilton_seed_plan.json", seed_plan)
            write_json(b_ws / ".hamilton_budget.json", {
                "schema_version": 1,
                "max_total_evals": per_run,
                "retry_policy": "one_retry_only_when_engine_evaluations_zero",
            })
            jobs.append({
                "arm": "bare_pysr",
                "task_id": task_id,
                "repeat_id": repeat,
                "seed": seed,
                "root": rel(b_root),
                "workspace": rel(b_ws),
                "state": "ready_waiting_runtime_authorizations",
                "commands": [[
                    "python", rel(BASELINE_EXEC), "--workspace", rel(b_ws),
                ]],
                "requires": ["pysr_julia_authorization"],
            })

    matrix = {
        "schema_version": 1,
        "experiment_id": manifest["experiment_id"],
        "execution_permitted": False,
        "execution_order": "arms_independent",
        "job_count": len(jobs),
        "jobs": jobs,
    }
    write_json(output / "run_matrix.json", matrix)

    lock = {
        "schema_version": 1,
        "experiment_id": manifest["experiment_id"],
        "execution_permitted": False,
        "hashes": {
            rel(path): sha256(path)
            for path in (
                HERE / "pilot_manifest.yaml",
                HCC_CONFIG,
                BASELINE_EXEC,
                output / "run_matrix.json",
            )
        },
        "inputs": {task_id: specs["tasks"][task_id]["input_sha256"] for task_id in tasks},
    }
    write_json(output / "freeze_lock.json", lock)
    return lock


if __name__ == "__main__":
    print(json.dumps(build(), indent=2, ensure_ascii=False))
