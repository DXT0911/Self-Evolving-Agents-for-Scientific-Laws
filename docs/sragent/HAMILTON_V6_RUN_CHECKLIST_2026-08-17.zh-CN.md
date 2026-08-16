# Hamilton v6 因果消融运行清单

日期：2026-08-17
性质：dev pilot（开发试验，非确认性结论）
设计文档：`HAMILTON_V6_CAUSAL_ABLATION_DESIGN_2026-08-16.zh-CN.md`

本清单覆盖从授权到结果归因的完整流程。执行前请逐节确认。

## 1. 前置条件

| 项 | 要求 |
|---|---|
| Python 环境 | 已 `pip install -r requirements.txt`（或 `uv sync`），含 `pysr` / `sympy` / `pandas` / `numpy` / `pyyaml` / `openai` |
| Julia + PySR | `from pysr import PySRRegressor` 可导入并完成首次编译（首个 warm worker 冷启动约需数分钟） |
| 离线契约测试 | 先跑通过：`python -m unittest playground.hamilton.core.test_atomic_policy playground.hamilton.core.test_standard_runner playground.hamilton.core.test_warm_start_runner playground.hamilton.core.test_governed_policy playground.hamilton.core.test_config_catalog playground.hamilton.core.test_pysr_preflight` |
| API Key | 仅 arm C（LLM Hamilton）需要：`$env:HAMILTON_API_KEY = "..."`（PowerShell）或 `export HAMILTON_API_KEY=...`（bash）。arm A/B 零 token、不需要 key |
| Git 状态 | 分支 `experiment/hamilton-pysr-v6`，`git status` 干净 |

## 2. 授权开关

bundle 已冻结为 `execution_permitted: false`。授权是显式的一步：

1. 打开 `experiments/hamilton_vs_pysr_governed_search_v6/pilot_bundle/run_matrix.json`；
2. 把顶层 `"execution_permitted"` 从 `false` 改为 `true`；
3. 同步把 `freeze_lock.json` 顶层的 `"execution_permitted"` 改为 `true`；
4. （可选，记录用）把 `pilot_manifest.yaml` 的 `status` 改为 `authorized`。

这一步是**人为决策**：一旦授权，18 个 job 总计消耗最多 81,000 requested evaluations
（每 job 4,500）+ arm C 最多 6×60,000 LLM token。请只在确认预算可接受后执行。

> 说明：`execute_governed_hamilton.py` 不硬性读取该开关；它是流程级门禁。切勿在未授权时启动 arm C（会真实调用 DeepSeek 计费）。

## 3. 实验矩阵（18 个 job）

| arm | 干预来源 | LLM | 任务 × seed |
|---|---|---:|---|
| `arm_a_persistent_pysr` | 无（always continue） | ✗ | static_s02 / dynamic_d01 × 8401/8402/8403 |
| `arm_b_rule_hamilton` | 确定性规则 | ✗ | 同上 |
| `arm_c_llm_hamilton` | LLM 原子动作（controller 采纳/拒绝） | ✓ | 同上 |

每 job = 3 轮 × 1500 requested evals，warm-start 贯穿；arm C 在轮 1、2 各调一次 planner（末轮无下一轮可作用，不调）。

## 4. 逐 arm 命令

统一命令模板（在仓库根目录执行）：

```powershell
python experiments/hamilton_vs_pysr_governed_search_v6/execute_governed_hamilton.py `
  --workspace experiments/hamilton_vs_pysr_governed_search_v6/pilot_bundle/<arm>/<task>/<repeat>/workspace `
  --arm <arm>
```

其中 `<arm>` ∈ `{arm_a_persistent_pysr, arm_b_rule_hamilton, arm_c_llm_hamilton}`，
`<task>` ∈ `{static_s02, dynamic_d01}`，`<repeat>` ∈ `{repeat_1, repeat_2, repeat_3}`。

### 建议顺序

先跑 **arm A + arm B**（零 token、验证链路 + restart 是否正确触发），再跑 **arm C**（计费）。

**全部 18 个 job 的顺序循环（bash，PowerShell 见下）：**

```bash
cd <仓库根目录>
for arm in arm_a_persistent_pysr arm_b_rule_hamilton arm_c_llm_hamilton; do
  for task in static_s02 dynamic_d01; do
    for rep in repeat_1 repeat_2 repeat_3; do
      ws="experiments/hamilton_vs_pysr_governed_search_v6/pilot_bundle/$arm/$task/$rep/workspace"
      echo "=== $arm $task $rep ==="
      python experiments/hamilton_vs_pysr_governed_search_v6/execute_governed_hamilton.py \
        --workspace "$ws" --arm "$arm" || echo "FAILED: $arm $task $rep"
    done
  done
done
```

**PowerShell 等价：**

```powershell
$arms = "arm_a_persistent_pysr","arm_b_rule_hamilton","arm_c_llm_hamilton"
$tasks = "static_s02","dynamic_d01"
$reps = "repeat_1","repeat_2","repeat_3"
foreach ($arm in $arms) {
  foreach ($task in $tasks) {
    foreach ($rep in $reps) {
      $ws = "experiments/hamilton_vs_pysr_governed_search_v6/pilot_bundle/$arm/$task/$rep/workspace"
      Write-Host "=== $arm $task $rep ==="
      python experiments/hamilton_vs_pysr_governed_search_v6/execute_governed_hamilton.py --workspace "$ws" --arm "$arm"
    }
  }
}
```

### 最小 smoke（可选，先验证端到端 + restart 路径）

只跑 `static_s02 × repeat_1` 的三臂，确认因果路径与冷重启均正常后再铺满：

```powershell
python experiments/hamilton_vs_pysr_governed_search_v6/execute_governed_hamilton.py --workspace experiments/hamilton_vs_pysr_governed_search_v6/pilot_bundle/arm_a_persistent_pysr/static_s02/repeat_1/workspace --arm arm_a_persistent_pysr
python experiments/hamilton_vs_pysr_governed_search_v6/execute_governed_hamilton.py --workspace experiments/hamilton_vs_pysr_governed_search_v6/pilot_bundle/arm_b_rule_hamilton/static_s02/repeat_1/workspace --arm arm_b_rule_hamilton
python experiments/hamilton_vs_pysr_governed_search_v6/execute_governed_hamilton.py --workspace experiments/hamilton_vs_pysr_governed_search_v6/pilot_bundle/arm_c_llm_hamilton/static_s02/repeat_1/workspace --arm arm_c_llm_hamilton
```

## 5. 超时与重试边界

| 边界 | 值 | 位置 |
|---|---|---:|
| 单轮 PySR 超时 | 21,600 s（6 h） | `execute_governed_hamilton.py` 的 `subprocess.run(timeout=21600)` |
| warm worker 启动超时 | 180 s | `run_experiment.py::_start_warm_worker` |
| 每 job 重试 | 最多 1 次，且仅当 `engine_measured_evaluations == 0`（干净失败，无已消耗算力） | executor 内 `attempts >= 2 or engine_evals(result) != 0` |
| LLM 调用重试 | `max_retries=2`，单次 `timeout=120` | `compressed_planner.call_atomic_planner` |
| LLM token 硬上限 | 每 arm-C run 60,000（超限抛错） | `call_atomic_planner(max_total_tokens=60000)` |
| 评估 ledger 上限 | 每 seed 6,000（超限 runner 抛错） | `.hamilton_budget.json` |

**重试策略**：某一 job 失败时，不要手动补跑中间轮——executor 已按「零 engine 才算干净失败」的原则内建一次重试。
若失败发生且 `engine_evals > 0`（算力已消耗），不得 top-up 补跑，否则破坏配对预算；应记录该 job 为 failed，在归因时单独披露。

## 6. 结果收集与归因

全部（或部分）job 完成后：

```powershell
python experiments/hamilton_vs_pysr_governed_search_v6/collect_pilot.py
```

产出 `pilot_bundle/pilot_evidence.json`，含：

- `rows`：每 job 的最终 scientific score、engine evals 总量、LLM token、planner 调用数、LLM 采纳/拒绝次数、binding action 分布；
- `paired_comparisons`：每个 (task, seed) 上 A/B/C 三臂的 score 与 engine evals；
- `head_to_head`：`c_vs_a`、`c_vs_b`、`b_vs_a` 的胜/负/平计数。

**归因规则（预注册，不可后补）**：

- `C − A` = LLM 总增益；`C − B` = LLM 相对规则策略的增量；`B − A` = 规则/controller 增量；
- 成功判据：C 在多数 paired seed 上同时优于 A 与 B，且优势**不能**由更多 engine-measured evaluations 解释（`collect_pilot` 会输出每臂 engine evals 供你核对）；
- 否则诚实结论为「当前 LLM 干预策略没有增量价值」，而不是继续加 token 或自由度。

每 job 的详细证据在 `<workspace>/v6_governed_summary.json`（逐轮 binding action、incumbent、engine evals）；arm C 另在
`<workspace>/.hamilton_atomic_planner_ledger.json` 与 `<workspace>/history/roundN/atomic_planner_proposal.json`
记录每次 planner 提议与采纳/拒绝结果。

## 7. 验证 restart 是否真的触发

cold-restart 只会在 arm B/C 采纳 `add_operator`/`remove_operator`（或 arm C 采纳 `restart_same`）时发生。
运行后按以下方式确认：

- `v6_governed_summary.json` 的 `rounds[].binding_action.requires_restart == true` 表示该轮冷重启；
- 对应轮 `roundN/results/result.json` 的 `warm_start_transition.restarted == true`；
- 若 arm C 三臂全 `continue_warm`（无 restart、无 operator 变更），则因果路径虽已打通但 LLM 未使用它——这本身就是有效结果，按第 6 节判据诚实收场。

## 8. 成本预估

- LLM：仅 arm C，每 run ≤ 60,000 token（实际约 5,000），6 runs 保守约 ¥0.05（按 DeepSeek 官方价）。
- 算力：18 jobs × 3 轮 PySR，静态任务单轮较慢；按 v5 经验预计每 job 数十分钟到数小时量级。
