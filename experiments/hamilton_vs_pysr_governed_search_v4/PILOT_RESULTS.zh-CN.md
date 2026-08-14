# Hamilton v4 三 seed 开发 pilot 结果

日期：2026-08-14
任务：`static_s01`（公开开发任务）
性质：开发 pilot，不是确认性证据；未使用 VIV、sealed test 或 OOD 数据。

## 结论

这次优化出现了值得继续验证的正向信号，但还不能说 Hamilton 已经稳定优于 PySR。

- 对同 seed ordinary PySR：Hamilton 为 **2 胜 1 平**，scientific score 的配对中位相对改善为 **22.73%**。
- 对同 seed fixed restart：也是 **2 胜 1 平**；Hamilton 的平均 engine-measured evaluations 反而少约 **9.8%**，因此这是当前最可信的正向证据，支持持久 warm-state continuation 优于重复重启。
- 对 union-operator restart：Hamilton 为 **2 胜 1 负**，但 union 的 seed 方差很大，不能据此排除扩展算子包络。
- 三 seed 太少；对 ordinary 的两个非平局 pair 做双侧 sign test 也不会显著（`p=0.5`）。本结果只能作为扩大实验前的 go signal。

本 pilot 的所有 binding 决策都是 `initialize/continue`，没有触发 `modify`。因此观察到的收益来自确定性治理与持久搜索状态，不是 LLM 提出的结构干预。

## 配对结果

scientific score 越低越好。

| seed | Hamilton | ordinary | fixed restart | union restart | Hamilton vs ordinary |
|---:|---:|---:|---:|---:|---|
| 8201 | 0.098971 | 0.098971 | 0.098971 | 0.194164 | 平 |
| 8202 | 0.137795 | 0.178332 | 0.178332 | 0.078456 | 胜 22.73% |
| 8203 | 0.011305 | 0.017829 | 0.017829 | 0.453868 | 胜 36.59% |
| 均值 | **0.082691** | 0.098377 | 0.098377 | 0.242163 | — |
| 中位数 | **0.098971** | 0.098971 | 0.098971 | 0.194164 | — |

seed 8203 的 Hamilton 最终式为：

```text
0.49999532*x1*x2**2
```

它在内部 validation 上非常好，但 controller-only challenge grid 的严格 ground-truth equivalence 阈值未通过：normalized RMSE 为 `9.36e-6`，高于冻结阈值 `1e-8`。因此报告为“近似恢复”，不能报告为精确恢复。

## 实际计算量

requested evaluations 在所有 arm/seed 都严格为 3,000，但 PySR 的实际测量评估数存在量化差异。

| arm | 平均 engine-measured evaluations | 相对 Hamilton |
|---|---:|---:|
| governed Hamilton | 4344.3 | 1.000 |
| ordinary PySR | 3510.0 | 0.808 |
| fixed restart | 4814.0 | 1.108 |
| union restart | 4260.0 | 0.981 |

因此：

1. Hamilton 对 ordinary 的结果受实际计算量混杂，不能单独当作算法优势；下一阶段应同时冻结 requested 与 engine-measured tolerance。
2. Hamilton 对 fixed restart 的优势没有这个方向的混杂，因为 fixed 实际计算更多但结果更差或持平。
3. fixed/union 的同 seed 三次重启结果完全重复，说明固定 seed 重启没有提供多样性；后续若保留 restart arm，应使用冻结但不同的 episode seeds，或明确把它当作确定性重复性审计而非搜索基线。

## 额度与运行审计

- 成功 requested evaluations：`36,000 / 36,000`
- failed attempts：`0`
- Hamilton warm-state preserved：`9 / 9` rounds
- binding action 在评估预留前执行：是
- LLM token：`0 / 90,000`
- 测试：`116 passed`

LLM token 为 0 不是遗漏。冻结策略将 LLM 权限降为 advisory-only；本 pilot 没有出现必须由 planner 决定的分支，而且旧 v3 每轮实际消耗约 76k–145k tokens，无法在每 seed 30k 的授权内可靠闭合。为避免“为了花额度而调用模型”，本轮由 binding controller 直接执行。由此，本结果验证的是 **Hamilton v4 governed controller**，尚未验证 LLM planner 的增量价值。

## 暴露的新问题

1. `material_residual_correlation` 在残差幅值已极小时仍可能接近 1。seed 8203 的近精确式就出现该现象；策略必须先通过残差幅值/误差 gate，再允许相关性触发结构干预。
2. ordinary 与 warm segmented run 的 engine-measured evaluations 不完全相等。下一 pilot 应把差异限制在例如 ±5%，或采用 engine-measured stop 进行配对。
3. 三 seed、单任务不足以评价稳定性和跨任务泛化。
4. 本轮没有触发 `modify`，所以尚未验证 binding policy 的干预质量。

## 建议的下一步（尚未执行）

建议继续，但不要直接扩大到确认性实验。先做一个修订 pilot：

1. 给残差结构信号增加 validation NRMSE 或残差尺度 gate。
2. 用 engine-measured tolerance 配平 Hamilton 与 ordinary。
3. fixed restart 改为预冻结的不同 episode seeds。
4. 选择至少一个能稳定触发 `modify` 的公开开发任务，验证策略干预而不只是 continuation。
5. 扩到至少 10 paired seeds、2–3 个公开开发任务后，再判断是否进入确认性阶段。

机器可读证据见 `pilot_evidence.json`，冻结预算轨迹见 `pilot_bundle/paired_budget_trace.json`。
