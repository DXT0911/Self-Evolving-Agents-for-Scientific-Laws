# Hamilton P0 多轮闭环验收（2026-07-22）

## 结论

严格治理下的多轮闭环验收通过。这里的“通过”表示 Round 2 和 Round 3 都形成了
可机器审计的 Discovery/Verification/Promotion/Finish 闭环；它不表示已经满足科学成功
标准。最终 Agent 正确返回 `task_completed=false`。

## 可复现身份

- Git commit：`a9f5164ff0bf80296471b9089c864ebcf2ebff5e`
- 配置：`configs/hamilton/config_controlled_long.yaml`
- 任务：`docs/sragent/CONTROLLED_LONG_RUN_TASK.md`
- run：`runs/hamilton_controlled_long_retry1_20260720`
- 最终记录：`records/experiment_20260722_112301.json`
- 模型：`deepseek-v4-pro`
- PySR：1.5.9
- Julia：1.11.9
- Python：3.13.5
- 随机种子：42

完整 run workspace、LLM trajectory、PySR checkpoint 和候选表按研究协议保留在本地，
不提交 Git。

## 治理结果

| 轮次 | 唯一变化 | closure | scientific success | 决策 |
|---|---|---:|---:|---|
| 2 | `search.binary_operators` | true | false | 拒绝 R2，保留 R1 |
| 3 | `search.niterations` | true | false | 拒绝 R3，保留 R1 |

Round 3 仅把 `search.niterations` 从 500 改为 2000。为兼容旧结果 schema，配置显式
关闭 `data.standardize_search` 和 `verification.residual_diagnostics`；controller 将“legacy
缺失”与“显式关闭”规范化为相同语义，因此它们不计为适应变量。

Round 3 消耗 167,622 Discovery/Verification tokens 和 285,871 Promotion tokens，共
453,493 tokens。独立 Promotion 预算没有与 Discovery 串账。

## 科学结果

Round 3 结果状态为 `completed`，只使用 `input/U248_train.csv`，连续 20% 尾段用于内部
验证。选中式为：

```text
-137.736032550386*x - 0.261987936516262*(x + 0.13785033)^3 - 29.1217656
```

- scientific score：1.238153692448005
- train R²：0.49843039421668167
- validation R²：0.527772820063314
- 方程仍不含 `v`
- 10 秒 ODE 验证完成，但不足以构成科学成功

因此“仅增加迭代次数即可从 x-only 搜索进入含 v 表达式”的假设被证伪。R1 的
scientific score 约 0.965，仍优于 R2/R3，故 incumbent 被正确保留。

## 隐私与失败审计

- 未读取、复制或使用 controller-private test/OOD 数据。
- 未把私有 test/OOD 结果用于算子、超参数、prompt 或候选选择。
- 两个无效 Round 3 尝试均保留在 round3 的 `rejected_*` 隔离目录，没有删除：
  - 首次尝试实际改变四个 leaf fields，被单变量治理拒绝；
  - 第二次尝试暴露新版 runner 默认字段与 legacy schema 的语义差异，被治理拒绝。
- JuliaPkg 原共享 project 存在 Windows 锁/权限问题；最终使用 run 内隔离 project
  完成预热，preflight 用时 11.272 秒且不消耗 LLM tokens 或 PySR evaluations。

## 本次验收暴露并修复的问题

1. Promotion 的真实治理写回需要显著高于 30k 的 token 预算。
2. Promotion 重试必须明确要求三份记录在当前尝试中都发生恢复写入。
3. 新旧 runner schema 比较必须区分“新增默认行为”和“显式关闭等价于 legacy 缺失”。
4. JuliaPkg 的 `lock.pid` 不能仅用通用 `filelock` 探测来断言可用性。

第 4 项仍应作为后续 preflight 实现改进；本次只使用隔离 project 绕过环境锁，没有
放宽科学治理或隐私边界。
