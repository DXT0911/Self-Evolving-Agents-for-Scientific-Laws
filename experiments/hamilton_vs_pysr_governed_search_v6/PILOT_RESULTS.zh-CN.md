# Hamilton v6 三臂因果消融开发试验结果

日期：2026-08-17
性质：开发集 dev pilot（3 seeds），不是确认性结论

## 结论先行

v6 首次给 LLM 一个受控但真实的原子动作空间（continue_warm / adjust_parsimony /
add_operator / remove_operator / restart_same），controller 审核后采纳/拒绝。结果：

- **C（LLM Hamilton）相对 A（persistent PySR）：5 胜 1 负**；
- **C 相对 B（rule Hamilton）：5 胜 1 负**；
- **B 相对 A：6 平**——规则在三轮内从未触发干预。

跨 v1–v5 第一次观察到 LLM 的一致正向增益，且**不能用更多 engine-measured evaluations
解释**。但两个重要限制：一是 3-seed dev pilot（非确认性），二是 B 与 A 完全一致（规则
baseline 退化），因此只能下「LLM > 什么都不做」的结论，还不足以说「LLM > 最佳规则」。

## 归因

scientific score 越低越好。

| 任务 | seed | A | B | C | 胜者 |
|---|---|---:|---:|---:|---|
| dynamic_d01 | 8401 | 0.70664 | 0.70664 | **0.64750** | C |
| dynamic_d01 | 8402 | 0.87247 | 0.87247 | **0.64166** | C |
| dynamic_d01 | 8403 | 0.31481 | 0.31481 | **0.30346** | C |
| static_s02 | 8401 | **0.24538** | 0.24538 | 0.38645 | A |
| static_s02 | 8402 | 0.54069 | 0.54069 | **0.37060** | C |
| static_s02 | 8403 | 0.68914 | 0.68914 | **0.61540** | C |

head-to-head（wins/losses/ties）：

- C vs A：5 / 1 / 0
- C vs B：5 / 1 / 0
- B vs A：0 / 0 / 6

## 计算量混杂检查

| 任务 | seed | A engine evals | C engine evals | C−A |
|---|---|---:|---:|---:|
| dynamic_d01 | 8401 | 8768 | 8862 | +1.1% |
| dynamic_d01 | 8402 | 6842 | 6970 | +1.9% |
| dynamic_d01 | 8403 | 6836 | 7425 | +8.6% |
| static_s02 | 8401 | 7841 | 7568 | −3.5% |
| static_s02 | 8402 | 7883 | 8025 | +1.8% |
| static_s02 | 8403 | 7560 | 7453 | −1.4% |

C 相对 A 的 engine evals 差异在 ±9% 内，方向不固定，无系统性的计算优势。特别是
dynamic_d01/8402 上 C 只多用 1.9% 计算却把 score 从 0.872 降到 0.642（约 26% 改善），
不能用计算量解释。

## LLM 动作机制（arm C 逐 seed）

| 任务 | seed | LLM round 1 | LLM round 2 |
|---|---|---|---|
| dynamic_d01 | 8401 | add_operator tanh（重启） | adjust_parsimony 0.0001 |
| dynamic_d01 | 8402 | add_operator tanh（重启） | continue_warm |
| dynamic_d01 | 8403 | adjust_parsimony 0.01 | add_operator tanh（重启） |
| static_s02 | 8401 | adjust_parsimony 0.01 | add_operator tanh（重启） |
| static_s02 | 8402 | continue_warm | add_operator tanh（重启） |
| static_s02 | 8403 | adjust_parsimony 0.01 | continue_warm |

- 6 个 seed 中 5 个 LLM 提议了 `add_operator tanh`（触发冷重启），这正是 v1 唯一一次
  正信号的方向；其余为 `adjust_parsimony` 或 `continue_warm`。
- 12 次 LLM 提议全部被 controller 采纳（0 拒绝），全部落在冻结 envelope 内。
- restart 路径（算子变更 → warm worker 重建模型）在 5/6 seed 上端到端跑通。

## B==A 的原因（规则基线退化）

arm B 的规则 `choose_atomic_action` 复用 `choose_action` 的阈值：
`stale_rounds_before_intervention = 3`，且「incumbent 仍在改善就 continue」。在只有 3 轮的
pilot 里，规则需要 2 轮以上的停滞才会干预，而绝大多数 seed 的 incumbent 持续改善，于是规则
每一轮都返回 `continue_warm`，与 A 的「always continue」完全一致。

后果：`C − B` 目前约等于 `C − A`，只能测「LLM 比什么都不做」，不能测「LLM 比最佳规则」。
要让 B 成为有意义的对照，需要降低停滞阈值，或给规则加一条确定性的算子变更规则。

## 操作偏差披露

- 首次运行中，arm C 的 restart 轮暴露了一个 bug：`warm_start_worker.py` 的
  `_scientific_projection` 未剔除 `search_session.compatible_change_fields`，导致 restart 轮
  把该字段从 `["search.parsimony"]` 切到 `["search.unary_operators"]` 时被误判为「不兼容字段
  变更」。已修复（`fix(sragent): allow restart rounds to switch compatible_change_fields`），
  并新增回归测试。5 个受影响的 arm C job 已重置并重跑成功。
- 授权开关 `execution_permitted` 已在运行前翻为 `true`。

## 解释边界与下一步

本次是 dev pilot（3 seeds），按交接文档 §13 的最低要求，确认性结论需要 ≥10 paired seeds。
当前证据支持：**打通因果路径后，LLM 的结构干预（加 tanh、调 parsimony）在多数 seed 上稳定
优于 persistent PySR，且增益不能归因于更多计算**。

下一步（确认性）应：

1. 扩到 ≥10 paired seeds；
2. 修复 B 基线（降 `stale_rounds_before_intervention`，或加确定性算子规则），使
   `C − B` 成为有意义的「LLM vs 规则」对照；
3. 继续匹配 requested 与 engine-measured evaluations；
4. 预注册成功判据后执行，不可事后放宽。
