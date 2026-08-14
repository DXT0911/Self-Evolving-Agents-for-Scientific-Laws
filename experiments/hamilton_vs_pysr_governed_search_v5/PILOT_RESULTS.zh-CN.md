# Hamilton v5 完整链路开发试验结果

日期：2026-08-14
性质：开发集 pilot，不是确认性结论

## 结论先行

本轮达成了“完整 Hamilton 链路可运行”的工程目标：在新数据集 `static_s02`、3 个新 seed 上，
每轮均先由 binding controller 决定并执行动作，再进行恰好一次压缩 planner 调用，最后写入
evidence memory。9/9 次 DeepSeek 调用成功，9/9 轮 memory 成功落盘，controller 的最终执行权
没有被 planner 绕过。

性能上，Hamilton 相对 ordinary PySR 为 2 胜 1 负，相对 fixed schedule 为 2 胜 1 平，
相对 union schedule 为 3 胜 0 负。Hamilton 的中位 scientific score 为 `0.453598`，3-seed
均值为 `0.359189`。但全部 binding action 都是 `initialize/continue`，planner 建议没有改变实际
搜索配置或预算，因此本轮只能证明“持久 warm-state + controller 治理的 Hamilton 执行链有提升迹象”，
不能把提升归因于 LLM。

3 个 Hamilton 最佳式的后验真值等价检查全部失败。本轮没有恢复严格真实公式，不能把较低 score
解读为符号恢复成功。

## 实现内容

- 新增压缩 planner：`playground/hamilton/core/compressed_planner.py`。
- 模型固定为 `deepseek-v4-flash`，关闭 thinking，JSON 输出，温度 0，每轮最多一次调用。
- 发送内容限于脱敏聚合诊断、匿名变量/算子允许列表和前轮弱假设；不发送原始行、方程、系数、
  项文本、配置、路径或结果哈希。
- planner 只写入 advisory proposal，现有 proposal validator 和 token ledger 继续生效。
- 每轮执行后调用 evidence-memory writer，写入 strong search outcome 与 weak causal hypothesis。
- binding controller 先于 planner 执行，planner 无权改写 config、budget、promotion 或最终 action。
- residual intervention 增加最小 validation NRMSE 门槛，避免在近零残差上被相关系数噪声误触发。

## 冻结设计与额度

| 项目 | 冻结值 |
|---|---:|
| 数据集 | `static_s02`（不同于上轮 `static_s01`） |
| seeds | 8301、8302、8303 |
| arms | Hamilton、ordinary、fixed、union |
| 正式 requested evaluations | 54,000 |
| Hamilton planner calls | 9 |
| LLM token 硬上限 | 180,000（每 seed 60,000） |
| 实耗 token | 5,120（2.844%） |
| 输入 / 输出 token | 3,774 / 1,346 |
| 保守 cache-miss 费用 | ¥0.006466 |

费用按 DeepSeek 官方价格快照计算：输入 cache miss ¥1/百万 token、输出 ¥2/百万 token。
模型与接口能力依据官方文档：

- https://api-docs.deepseek.com/quick_start/pricing/
- https://api-docs.deepseek.com/api/list-models
- https://api-docs.deepseek.com/api/create-chat-completion

## 配对成绩

scientific score 越低越好。

| seed | Hamilton | ordinary | fixed | union |
|---:|---:|---:|---:|---:|
| 8301 | 0.453598 | **0.418498** | 0.453598 | 0.487998 |
| 8302 | **0.459983** | 0.679757 | 0.679757 | 0.642576 |
| 8303 | **0.163986** | 0.245375 | 0.245375 | 0.672604 |

相对 ordinary 的中位相对改善为 32.33%；但 Hamilton 的平均引擎实测评估数为 7,905，ordinary
为 5,179，约多 52.64%。对 fixed 的评估量更可比，Hamilton 为 2 胜 1 平；这更直接支持
持久 warm-state 在 seed 8302/8303 上优于同 seed 的独立重启。

## planner 与 memory 审计

| seed | calls | token | memory 更新轮 | strong outcomes | weak hypotheses |
|---:|---:|---:|---:|---:|---:|
| 8301 | 3 | 1,797 | 3 | 3 | 3 |
| 8302 | 3 | 1,724 | 3 | 3 | 3 |
| 8303 | 3 | 1,599 | 3 | 3 | 3 |

memory 文件位于各 Hamilton workspace：

`pilot_bundle/governed_hamilton/static_s02/repeat_N/workspaces/task_0/.hamilton_evidence_memory.json`

planner ledger 位于同目录的 `.hamilton_planner_ledger.json`，逐调用 proposal 位于
`history/roundN/planner_proposal.json`。

## 操作偏差披露

正式结果文件恰好对应 54,000 requested evaluations，全部完成且无 failed ledger attempt。
运行 union/seed 8302 时，外壳超时后残留的子进程仍继续运行；错误地启动第二实例导致 episode 1
被同配置重复执行一次，ledger 多出 1,500 次已完成 requested evaluations。正式配对只使用最终登记的
3 个 episode，重复开销单列为 operational duplicate，实际 ledger 总量因此为 55,500。

另有两次脚本路径写错，在 Python 找不到入口时即退出，engine=0；它们未进入结果 ledger，也未消耗
DeepSeek token。

## 还能怎样省 token

按收益与风险排序：

1. **取消末轮 planner。** 当前末轮 proposal 没有下一轮可以执行，3 个末轮共 1,885 token，直接可省
   36.82%。若需要末轮反思，应使用无 LLM 的 deterministic summary。
2. **事件触发而非逐轮触发。** 仅在 controller 进入 `modify/branch`、诊断量跨阈值或前假设已被检验时
   调用。本轮所有 action 都是 continue；生产模式严格按 controller intervention 触发时可省 100%，
   但保留首轮 baseline call 更利于持续验证接口。
3. **假设去重。** 9 次调用只有 6 个不同的 hypothesis；seed 8302/8303 后轮出现完全重复，seed 8301
   后两轮语义也高度重复。诊断快照变化小且旧假设仍是 `untested` 时直接复用，至少可覆盖本轮 3 个末轮调用。
4. **不回传前轮长文本。** 第 3 轮总 prompt 为 1,433 token，第 1 轮为 1,089；改为 hypothesis hash、
   operator bitmask 和少量 delta 字段，可再去掉约 344 个 prompt token（本轮总量约 6.72%）。
5. **把输出上限从 800 降到 256。** 本轮单次 completion 最大 176 token，256 留有约 45% 余量；
   同时将 hypothesis/falsification 改为短枚举和定长字段，减少模型生成冗余 prose。
6. **利用稳定系统前缀缓存。** 缓存降低费用而不是 token 计数；官方 cache-hit 输入价明显低于 miss，
   适合固定 system/schema 前缀。

不建议跨 seed 合批，因为它会削弱配对独立性并增加信息泄漏边界。

## 解释边界与下一步

这次完整验证中 LLM 确实被调用、其假设确实进入每轮 memory，但它没有因果执行权，也没有触发
controller 的新动作。因此“完整”指工程数据流完整，不等于“LLM 已贡献性能”。下一轮若要验证 LLM
增益，应让 controller 在安全白名单内选择是否采纳 planner 的有限动作，例如从 2–3 个已批准 intervention
中挑选一个；仍由 controller 校验、限额并最终提交。随后做 `planner-on` 与 `planner-off` 的同 seed 消融，
才能回答 LLM 是否真的提高 Hamilton。

## 验证

- Hamilton/runner 相关测试：124 passed。
- `git diff --check`：无 whitespace error（仅有工作区 LF/CRLF 提示）。
- 后验 ground-truth challenge grid：3/3 不等价。
- 结构化原始汇总：`pilot_evidence.json`。
- 后验真值审计：`ground_truth_audit.json`。
