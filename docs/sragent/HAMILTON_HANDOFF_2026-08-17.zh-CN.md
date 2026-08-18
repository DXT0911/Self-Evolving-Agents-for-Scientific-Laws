# Hamilton 交接文档

日期：2026-08-17
状态：交接，供下一阶段研究继续

## 1. 项目是什么

**Hamilton** 是 EvoMaster 框架里的**符号回归（Symbolic Regression）Agent**，核心研究问题只有一个：

> **LLM 能不能在公平预算下、稳定地提升 PySR 的方程发现能力？**

仓库：`Self-Evolving-Agents-Hamilton-v2`，当前分支 `experiment/hamilton-pysr-v6`，PR #4（Draft）。

## 2. 本次对话完成了什么

### 2.1 v6 因果消融（给 LLM 打通因果路径）

交接文档 `HAMILTON_V1_V5_EXPERIMENT_SUMMARY_2026-08-14.zh-CN.md` 已说明 v1–v5 都没证明"LLM 提升 PySR"——v4/v5 里 LLM 是 advisory-only，proposal 从不进执行。本次做了：

- **打通因果路径**：新增 5 个原子动作白名单（`continue_warm` / `adjust_parsimony` / `add_operator` / `remove_operator` / `restart_same`）。LLM 提一个原子动作，controller 审核后采纳/拒绝，采纳后真正改变下一轮搜索。
- **核心代码**：`governed_policy.py`（`normalize_atomic_action` / `choose_atomic_action`）、`compressed_planner.py`（`call_atomic_planner`）、`search_control.py`（`review_planner_proposal` / `persist_binding_action`）、`run_experiment.py` + `warm_start_worker.py`（restart 轮 `model=None` 重建）。
- **三臂设计**：A persistent PySR（无 LLM）、B rule Hamilton（规则干预）、C LLM Hamilton。

#### 结果（重要，且是负结果）

- 3-seed pilot：C 对 A 5 胜 1 负（看似正向）。
- 扩到 **10 seed × 4 任务（40 配对）后反转：C 对 A 12 胜 25 负（符号检验 p=0.047），显著有害**；C 对 B 5 胜 19 负（p=0.007）。
- **根因**：LLM 过度提 `add_operator tanh`（80 次提议里 39 次），触发冷重启丢弃 warm 种群，而 tanh 常常不值这个代价。计算量检查排除了"靠更多算力"的解释。
- **结论**：当前"LLM 从脱敏快照提原子动作"的策略没有增量价值。证据见 `experiments/hamilton_vs_pysr_governed_search_v6/PILOT_RESULTS.zh-CN.md`。

### 2.2 转向 HCC 混合线路（用户决定）

用户判断：v6 效果不好 + 缺"直观可读的记忆文件"（plan.md/findings.md）。决定回到 HCC 线路（自由 LLM + 可读记忆 + 发现→验证→提炼闭环），但保留 v6 的测量纪律（配对 seed + engine evals + 预注册判据）。**决策：混合方案**。

HCC 线路主体是 `playground/hamilton/core/playground.py`（编排）+ `exp.py`（RoundExp 发现/验证）+ `promotion_exp.py`（PromotionExp 晋升/闭环）。

### 2.3 成本优化 + 可靠性修复

HCC 线路跑通（可读记忆质量很好），但暴露成本高（~48 万 token/轮）和 closure 不稳定。逐项修复：

| # | 问题 | 根因 | 修复 | 文件 |
|---|---|---|---|---|
| 1 | skill 文档太重 | SKILL.md 冗长 | 精简 -48% | `evomaster/skills/run-sr-experiment/SKILL.md` |
| 2 | 上下文 O(n²) 增长 | 每轮重发全部 tool 结果 | 新增 `tool_result_compaction` 策略（旧 tool 结果压成关键信息摘要）| `evomaster/agent/context.py` |
| 3 | findings/plan 写错路径 | 系统提示词"current round's"有歧义 | 显式声明文件布局 | `playground/hamilton/prompts/hamilton_system.txt` |
| 4 | 治理关掉后 closure 不稳定 | `scientific_governance: false` 把可靠性审计也关了 | 新增 `governance_mode: slim`（保留可靠性 gate、砍 VIV 严谨 gate）| `playground/hamilton/core/promotion_exp.py` |
| 5 | round 2 被 token 预算截停 | promotion 的 max_tokens 泄漏进 discovery | 发现阶段重置回 None | `playground/hamilton/core/playground.py` |
| 6 | round 2 撞 max_turns | 20 太紧 | 改回 60 | `config_hybrid_hcc_smoke.yaml` |

#### "瘦身治理"（governance_mode: slim）的边界

- **保留**（可靠性，保证可读记忆可信 + 运行稳定）：incumbent 保留、残差反馈如实、protocol 证据、plan 质量、单字段变更、失败 recovery。
- **砍掉**（VIV 专属严谨性）：claim 强度、scale 诊断、scientific success gates、`EVO_NEXT_ROUND` 11 字段契约。

配置写法：`experiment.governance_mode: slim`（兼容旧 `scientific_governance: true/false`）。

#### 成果

**Round 1 首次完整闭环**（`closed: True`，所有 gate 全绿，找到方程 score 0.676 vs 基线 0.769），并成功进入 Round 2。HCC 线路在 benchmark（static_s02）上端到端跑通了。

### 2.4 部署化设计（已写文档，未实现）

`docs/sragent/HAMILTON_DEPLOYABLE_AGENT_DESIGN_2026-08-17.zh-CN.md`：把 Hamilton 变成"数据 → 一条命令 → 方程"的可部署 agent。留了 3 个取舍待拍板：
1. 引擎默认：HCC 还是也带 controller 模式？
2. 默认模型：deepseek-v4-pro 还是 v4-flash？
3. 部署优先：Docker 还是 pip？

## 3. 关键文件

| 文件 | 作用 |
|---|---|
| `configs/hamilton/config_hybrid_hcc_smoke.yaml` | HCC 混合线路 smoke 配置（`governance_mode: slim`、max_turns 60、上下文压缩）|
| `playground/hamilton/core/playground.py` | HCC 循环编排 |
| `playground/hamilton/core/promotion_exp.py` | 瘦身治理（slim mode）|
| `playground/hamilton/core/governed_policy.py` / `search_control.py` / `compressed_planner.py` | v6 因果消融的原子动作层（仍在，但当前研究主线是 HCC）|
| `evomaster/agent/context.py` | 上下文压缩策略 |
| `evomaster/skills/run-sr-experiment/SKILL.md` | 精简后的 runner skill |
| `runs/hcc_smoke/workspaces/task_0/` | 最近一次 smoke 的可读 plan/findings（跑在 static_s02 上，`runs/` 被 gitignore）|

## 4. git 状态

- 分支 `experiment/hamilton-pysr-v6`，全部已提交推送，PR #4（Draft，`experiment/hamilton-pysr-v3 ← experiment/hamilton-pysr-v6`）。
- 最近提交：`feat(sragent): add slim governance mode and clarify workspace file paths for HCC loop`。

## 5. 重要提醒

- **协作者有独立的 v6 分支** `codex/hamilton-v6-llm-led`（"LLM-led"路线：纯 warm-safe、无重启、controller 枚举候选 LLM 选择）。**不要和 `experiment/hamilton-pysr-v6` 搞混**，也不要去碰它。
- HCC 线路的**真实成本**：~30-40 万 token/轮（是 v6 的几十倍），这是"可读记忆 + 自由推理"的代价。
- 离线测试：`python -m unittest playground.hamilton.core.test_standard_runner`（93 passed）等可跑；`evomaster/agent/test_agent_context.py` 有 26 个预先存在的 mock 报错（跟本次改动无关）。
- 跑 HCC smoke 的流程：预置 `runs/hcc_smoke/workspaces/task_0/input/data.csv` + `task.md` → `python run.py --agent hamilton --config configs/hamilton/config_hybrid_hcc_smoke.yaml --task "..." --run-dir runs/hcc_smoke`。跑完常有孤儿 warm worker（`python.exe warm_start_worker.py`），要用 `Stop-Process` 清掉再删 `runs/hcc_smoke`。

## 6. 下一步（用户定的方向）

1. **正式实验**：用 `config_hybrid_hcc_smoke.yaml` 这套（slim governance + 上下文压缩 + max_turns 60）跑正式的多 seed 实验，回答"HCC 混合线路在 benchmark 上到底能不能稳定找到方程、成本可不可接受"。注意可能需要切 v4-pro 并决定 seed/任务规模。
2. **完成部署化设计**：拍板 3 个取舍（引擎/模型/部署），然后按设计文档实现 `hamilton discover` CLI + 数据接口 + 结果打包。

## 7. 结论性判断（供下一阶段参考）

- **v6 约束 planner（脱敏快照 + 原子动作）没有增量价值**——这是干净、可靠的负结论。
- **HCC 自由 LLM 的可读记忆质量很好**（真实方程 + 残差推理 + 替代解释 + 可证伪假设），但贵（~30-40 万 token/轮）。
- **HCC 的 closure 可靠性靠 governance 保证**——不能简单关掉；`governance_mode: slim` 是保留可靠性、砍 VIV 严谨的正确折中。
- 把 HCC 线路做稳、做便宜，是通往"可部署、能复现、跑出方程"这一最终目标的正确路径。
