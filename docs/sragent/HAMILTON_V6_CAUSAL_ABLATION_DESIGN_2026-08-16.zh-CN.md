# Hamilton v6 因果消融设计（草案）

日期：2026-08-16
状态：已冻结
- Q1 动作空间：全白名单（warm-safe + restart 类）
- Q2 实验规模：3-seed dev pilot（后续再扩 10-seed 确认性）
- Q3 数据集：static_s02 + dynamic_d01
性质：dev pilot 设计，不是确认性结论

## 1. 目标

把「LLM 是否在公平预算下稳定提升 PySR」设为唯一主要问题。v1–v5 已经证明工程底座可靠
（warm-start、binding controller、审计、压缩 planner），但从未证明 LLM 有因果增益——
因为 v4/v5 里 LLM 被设计成 advisory-only，其 proposal 从不进入下一轮执行。

v6 不是「给 LLM 更多自由」，而是「给 LLM 一个受控但真实的原子动作空间 + 一个可测的
采纳/拒绝环节」，然后做三臂 + planner-off 消融，把 LLM 增益从 warm-start 增益和
controller 增益里分离出来。

## 2. 三臂定义（冻结）

| 臂 | Persistent warm-start | Controller | LLM 可改变搜索 |
|---|---:|---:|---:|
| A：Persistent PySR | 是 | 仅预算 + 安全 + incumbent 保留 | 否 |
| B：Rule Hamilton | 是 | 规则 intervention | 否 |
| C：LLM Hamilton | 是 | 审核 LLM intervention | 是 |

- **A**：persistent warm-start PySR，controller 只做预算/安全/保留，不干预搜索动作。
  等价于「planner-off / controller-off」的最简对照，也等价于 v4/v5 的 Hamilton 底座。
- **B**：A + 确定性规则干预。规则在同一动作空间上决策（复用 `governed_policy.choose_action`
  的规则，或同空间的冻结规则表）。
- **C**：A + LLM 干预。LLM 在同一动作空间上决策，controller 审核后采纳/拒绝，保留回滚与
  最终提交权。

**关键约束**：B 与 C 必须共享同一动作空间，这样 `C − B` 才是「LLM 推理相对规则策略的增量」，
而不是「LLM 有更多动作可选」的假增益。A 与 C 的差异是「LLM 总增益」。

## 3. 动作白名单（LLM 与规则共用的原子动作）

| 动作 | 含义 | warm 兼容 | 触发冷重启 |
|---|---|---:|---:|
| `continue_warm` | 保持配置继续 persistent 搜索 | 是 | 否 |
| `adjust_parsimony` | 在冻结区间内把 `search.parsimony` 设为一个值 | 是 | 否 |
| `add_operator(op)` | 从冻结 envelope 向算子集合加入一个算子 | 否 | 是 |
| `remove_operator(op)` | 从当前集合删除一个算子 | 否 | 是 |
| `restart_same` | 同配置显式冷重启（逃离局部最优） | 否 | 是 |

- 每个动作最多改变**一个**搜索字段（trust-region `max_step_changes = 1` 维持不变）。
- `op` 必须来自冻结 envelope；parsimony 值必须落在冻结区间 `[min, max]`。
- 重复/无效动作（加已有算子、删不存在算子、区间外 parsimony）由 controller 拒绝。

**为什么把 operator 动作列为「触发冷重启」**：当前 warm worker 只允许跨轮变更
`search.parsimony`（`run_experiment.py:112-119`、`warm_start_worker.py:97-108`），
变更 `binary_operators`/`unary_operators` 会被 `_validate_transition` 判为不兼容而拒绝。
因此 v6 中 operator 动作等价于「用新算子集冷重启」。这是有意的权衡：v1 唯一一次正信号
（`tanh`）正是算子扩展，但当时也重启了。冷重启的成本（丢种群）会被 A/B/C 三臂同等承担，
并在归因时用 engine-measured evaluations 对齐，不做不公平对比。

**`restart_same` 在冻结同 seed 计划下是确定性 no-op**：种子计划用同一 seed 复现同一搜索，
`restart_same`（同配置 + 同 seed 冷重启）会精确重跑第 1 轮。其有意义的使用（换新 seed 逃离
局部最优）需要种子调度，留待确认性阶段。dev pilot 中 arm B 的规则不会触发它（`branch`/`rollback`
退化为 `continue_warm`）；arm C 的 LLM 仍可提议它，controller 会采纳，该 no-op 轮会被记录为证据。

## 4. 因果路径打通（核心代码改动）

### 4.1 planner 输出扩展

`compressed_planner.py`：在原有 5 字段之外，允许 planner 在冻结白名单内提议**一个**原子动作
（`requested_action` 从 `continue/modify/...` 改为 `continue_warm/adjust_parsimony/add_operator/
remove_operator/restart_same`），并携带对应参数（parsimony 值或算子名）。`validate_planner_proposal`
扩展为校验「动作 ∈ 白名单 ∧ 参数 ∈ 冻结 envelope ∧ 单字段」。

### 4.2 新增 controller 采纳/拒绝环节

`search_control.py` 新增 `review_planner_proposal(proposal, snapshot, control)`：

- 合法性校验（动作白名单、envelope、单字段、预算充足）。
- 若合法 → 返回 `{"adopted": true, "source": "llm", "action": proposal_action}`。
- 若非法/空/越界 → 返回 `{"adopted": false, "source": "rule", "action": choose_action(snapshot)}`
  （回退到确定性规则，绝不放行非法动作）。

controller 永远保留最终执行权：合法性、单变量变更、预算、回滚、最终提交。

### 4.3 采纳后写入 binding action → runner 强制执行

把 `review_planner_proposal` 的返回值**覆盖写回**
`state.next_round.controller_policy.action`（新增 `source: llm|rule` 字段），并同步写入
`plan.md` 的 `EVO_SCIENTIFIC_DECISION` 块。下一轮 `round_directive()` 与 runner 的
`expected_adaptive_config_patch()` / `audit_single_field_adaptation()` 会像 v5 一样强制执行它。
这一步是 v5 缺的关键一环：把 proposal 从「只写 memory」变成「写进执行」。

### 4.4 restart 类动作的处理（已定实现路径）

已确认：warm 复用只更新 `max_evals/niterations/maxsize/parsimony`，**不更新算子**（
`run_experiment.py:_run_experiment_with_model`）。因此 restart 类动作的干净实现是：

- `warm_start_session` 的 `round_action` 扩展为 `{initialize, continue, modify, restart}`；
- restart 轮的 `compatible_change_fields` 允许 `search.unary_operators` /
  `search.binary_operators` / `search.maxsize`（单字段）；
- `warm_start_worker.serve()` 见到 `round_action == "restart"` 时把 `model` 复位为 `None`，
  让 `_run_experiment_with_model` 用新算子集新建 `PySRRegressor`（`warm_start=True` 保留后续
  继续能力），并跳过算子字段的兼容性校验；
- 同一 worker/进程贯穿一个 seed（无孤儿子进程），`engine_evals_before` 继续累加，保证
  跨 restart 的总 compute 归因连续；
- `expected_adaptive_config_patch` / `audit_single_field_adaptation` 扩展支持 `restart` 动作。

restart 轮仍在同一 `session_id`、同一 `round` 序列内推进，只是模型重建；`restart_event`
写入 ledger 与 summary 以便归因区分 warm 继续 vs 冷重启。

## 5. 归因统计与成功判据（预注册）

- `C − A`：LLM 总增益（含 warm-start 与 controller 的净贡献）。
- `C − B`：LLM 相对规则策略的增量（隔离「LLM 推理」）。
- `B − A`：规则/controller 本身的增量（sanity check）。
- planner-off 消融：B 即 C 的 planner-off（同一动作空间，用规则取代 LLM 决策）。

**成功判据（开始前定义，不可后补）**：
C 在多数 paired seed 上同时优于 A 与 B，且优势不能用 engine-measured evaluations 更多来解释。
否则诚实结论为「当前 LLM 干预策略没有增量价值」。

每个 LLM 动作需记录：批准/拒绝、执行/回滚、后续 score 变化（delta）。

## 6. 冻结值（已定）

| 项目 | 冻结值 |
|---|---|
| 数据集 | static_s02 + dynamic_d01 |
| paired seeds | 8401 / 8402 / 8403（每任务同 3 个 seed） |
| 实验臂 | A：Persistent PySR、B：Rule Hamilton、C：LLM Hamilton |
| 每 arm/seed requested evals | 4500（每轮 1500 × 3 轮，与 v5 一致） |
| LLM 动作空间 | 全白名单：continue_warm / adjust_parsimony / add_operator / remove_operator / restart_same |
| planner 模型 | deepseek-v4-flash，温度 0，每轮 ≤1 次 |
| LLM token 硬上限 | 每 seed 60000（与 v5 一致） |
| parsimony 冻结区间 | [1e-8, 1.0]（与 v5 一致） |
| 算子 envelope | 初始 {sin, cos, exp}，可加入 {tanh}（union envelope 同 v5） |
| 轮数 | 3（planner 调用轮 1、2；末轮无下一轮可作用，不调 planner） |

## 7. 风险与未知

1. **operator 变更的 warm 兼容性**：PySR 是否支持 warm_start 下变更算子集需 preflight 验证。
   本设计默认「不支持 → 冷重启」，不赌未验证的引擎行为。
2. **冷重启丢种群**：restart 类动作会损失 warm 状态，可能抵消算子增益。这正是要测量的东西；
   A/B/C 三臂同受此影响，归因时按 engine-measured evals 对齐。
3. **LLM 仍可能全 continue**：打通因果路径不等于 LLM 一定给出有价值动作。若 C 全 continue 且
   与 B 无差异，这就是有效的阴性结果，按判据诚实收场。
4. **warm session 与冷重启的 round 编号交互**：需要显式 restart_event 记账，避免误导归因。

## 8. 实施步骤（设计定稿后）

1. 扩展 `compressed_planner.py` 的 proposal schema + `validate_planner_proposal`。
2. `search_control.py` 新增 `review_planner_proposal`（采纳/拒绝 + 回退规则）。
3. 扩展 `run_experiment.py` 的 `expected_adaptive_config_patch` / `audit_single_field_adaptation`
   以支持新动作类型与 restart_event（或新增 restart 分支）。
4. 新建 `experiments/hamilton_vs_pysr_governed_search_v6/`：
   `pilot_manifest.yaml` + `build_pilot.py` + `freeze_pilot_controls.py` +
   `execute_governed_hamilton.py`（三臂 A/B/C）+ `collect_pilot.py`。
5. 新增 `configs/hamilton/config_governed_pysr_v6_pilot.yaml`。
6. 契约测试：`test_governed_policy.py` 增加采纳/拒绝、envelope 越界、restart 记账用例。
7. 同步更新 `playground/hamilton/TODO.md` 与本文档状态。

## 9. 已确认

- **Q1 动作空间**：全白名单（warm-safe + restart 类）。
- **Q2 实验规模**：先 3-seed dev pilot，验证因果路径与 LLM 动作质量后再决定扩到 10-seed。
- **Q3 数据集**：static_s02 + dynamic_d01。
