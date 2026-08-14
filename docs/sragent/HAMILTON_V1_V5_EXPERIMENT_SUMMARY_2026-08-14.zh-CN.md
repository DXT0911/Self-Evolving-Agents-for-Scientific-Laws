# Hamilton v1–v5 实验总结

日期：2026-08-14

## 1. 总结结论

Hamilton 从 v1 到 v5 完成了从“高自由度 LLM 代理控制 PySR”到“确定性 controller 掌握最终执行权、LLM 只提供受限建议”的架构转变。系统的运行可靠性、审计能力和 token 效率显著改善，但最初的研究目标——**证明 LLM 能在公平预算下稳定提升 PySR**——尚未实现。

五代实验共同支持以下判断：

1. PySR 的跨轮 persistent warm-start 是目前最稳定、最可复现的性能来源。
2. 确定性预算、incumbent 保留、回滚和 binding policy 显著提高了运行可靠性。
3. LLM 曾在 v1 的 `dynamic_d01` 上提出加入 `tanh` 的有效干预，但该证据只有单次重复，且当时存在 token、协议和测量混杂。
4. v2、v3 没有显示 LLM 治理相对 ordinary PySR 的稳定优势，成本却非常高。
5. v4、v5 的正向结果主要来自 warm-state continuation 和 controller，而不是 LLM；v5 虽完成 9/9 次 planner 调用，但 planner 没有改变任何实际执行动作。
6. v1–v5 中没有一代在冻结的严格标准下稳定恢复真实方程。

因此，当前 Hamilton 是一个可靠的“受治理 persistent PySR”实验底座，但还不是一个已经被证实的“LLM 增强 PySR”方法。

## 2. 跨版本比较边界

v1–v5 使用了不同任务、seed 数量、evaluation 预算和评分实现，不能把不同版本的绝对 scientific score 直接排列成进步曲线。跨版本最适合比较的是：

- LLM 是否真正改变了下一轮搜索；
- 是否保留 PySR 搜索状态；
- 是否存在同 seed、同预算对照；
- token 和运行失败是否可审计；
- 是否进行了 controller-only 真值检查；
- 结论是否能与 LLM、warm-start 和计算量分别归因。

## 3. 总览

| 版本 | 核心问题 | 范围 | Hamilton LLM token | 主要结果 | 主要局限 |
|---|---|---|---:|---|---|
| v1 | 高自由度 LLM 能否控制 PySR | 3 个公开任务，各 1 repeat，3 arms | 2,751,149 | scientific score 对 ordinary 3 胜 0 负，对 fixed 2 胜 1 负；`dynamic_d01` 的 `tanh` 干预有效 | 单 repeat、无实测 evaluations、无严格真值验证、协议偏差 |
| v2 | 加入 union 对照和更严格运行门后是否仍有效 | 2 个任务，各 1 repeat，4 arms | 1,402,011 | static 上 Hamilton 胜 ordinary/fixed、负 union；dynamic 上明显负 ordinary/fixed | 三轮重启丢状态，LLM 调参不稳定，仍无精确恢复 |
| v3 | persistent warm-start 能否修复重启损失 | `static_s01`，1 seed，4 arms | 541,751 | warm-state 工作且胜 fixed；但负 ordinary 和 union | 单 seed；Promotion 未正常闭合；LLM 成本高、收益不足 |
| v4 | binding controller 和离线策略能否低成本稳定搜索 | `static_s01`，3 seeds，4 arms | 0 | 对 ordinary 2 胜 1 平，对 fixed 2 胜 1 平 | 没有调用 LLM；收益只能归因于 controller/warm-state |
| v5 | 压缩 planner、每轮 memory 和完整安全链路能否工作 | `static_s02`，3 seeds，4 arms | 5,120 | 对 ordinary 2 胜 1 负，对 fixed 2 胜 1 平，对 union 3 胜 0 负；9/9 planner 与 memory 成功 | planner 全为 advisory 且动作均 continue，不能证明 LLM 增益 |

## 4. v1：初始治理搜索运行门

### 设计

v1 在 `static_s01`、`dynamic_d01` 和 `viv_u248` 上各运行一次 governed Hamilton、ordinary PySR 和 fixed-schedule PySR。每个实验臂请求 12,000 evaluations，总请求预算为 108,000。Hamilton 先运行并形成 3 轮动态日程，基线复现相同累计预算。

### 结果

按 scientific score：

- Hamilton 对 ordinary：3 胜 0 负；
- Hamilton 对 fixed：2 胜 1 负；
- `dynamic_d01` 上 Hamilton 从残差诊断出发，在第三轮加入 `tanh`，验证 R² 从前两轮的 0.447、0.660 提升到 0.874；
- `viv_u248` 的优势主要来自短期轨迹评分，点值 NRMSE 反而略差，且没有恢复速度依赖。

v1 是五代中最接近“LLM 干预改变 PySR 并带来提升”的证据，因为 `tanh` 确实改变了搜索空间，随后指标改善。但它还不足以建立因果结论：每个任务只有一次重复，缺少 union 算子对照、engine-measured evaluations 和严格真值等价验证。

### 成本和问题

- DeepSeek token：2,751,149；
- 单 `static_s01` Hamilton 就使用 1,047,805 token；
- 运行中曾修改 Discovery/Promotion token 上限；
- Windows stdout 管道问题造成 Promotion 重读和额外 token；
- VIV 首轮先验中出现了不合规方程语法示例。

v1 证明了运行门可工作并产生正信号，但没有证明 Hamilton 普遍优于 PySR。

## 5. v2：四臂 operational gate

### 设计变化

v2 增加 union-schedule 对照，在 `static_s02` 和 `dynamic_d02` 上分别比较：

1. ordinary continuous PySR；
2. fixed schedule；
3. union operator schedule；
4. governed Hamilton。

每个实验臂请求 12,000 evaluations，共 96,000。Hamilton 分为 4,000 / 4,500 / 3,500 三轮，并允许 DeepSeek 根据验证和残差结果修改一个搜索参数。

### 结果

| 任务 | ordinary NRMSE | fixed | union | Hamilton |
|---|---:|---:|---:|---:|
| `static_s02` | 0.4402 | 0.4256 | **0.2364** | 0.2588 |
| `dynamic_d02` | **0.0583** | 0.0959 | 0.4257 | 0.2380 |

static 任务上 Hamilton 胜 ordinary 和 fixed，但略负 union；dynamic 任务上 ordinary 明显最好，Hamilton 只胜 union。没有任何方法精确恢复真实方程。

### 得到的关键认识

- 三轮独立重启丢失种群和候选积累，是相对 continuous PySR 的重大劣势；
- 将 `maxsize` 从 31 提到 41、随后提高 `parsimony`，均未改善 incumbent；
- 残差诊断可能正确，但“根据残差应该改哪个参数”的策略不可靠；
- static 与 dynamic 的最佳策略不同，说明单一调参规则缺乏跨任务稳定性。

Hamilton 两个任务共使用 1,402,011 token。v2 将问题从“LLM 能否生成动作”进一步定位为“动作是否真正有搜索价值”。

## 6. v3：persistent warm-start

### 设计变化

v3 的核心修复是让 Hamilton 三轮共享同一个常驻 `PySRRegressor(warm_start=True)` worker、种群、hall-of-fame 和随机状态。同时增加 `continue` 动作，不再强迫每轮修改参数。

试点使用 `static_s01`、seed 7101，四臂各完成 3,000 requested evaluations。

### 结果

| 排名 | 实验臂 | Scientific score | 验证 NRMSE | Engine-measured evaluations |
|---:|---|---:|---:|---:|
| 1 | ordinary | 0.1119 | 0.0812 | 3,876 |
| 2 | union | 0.1557 | 0.1267 | 4,539 |
| 3 | Hamilton | 0.2683 | 0.2183 | 4,306 |
| 4 | fixed | 0.3384 | 0.2965 | 3,903 |

Hamilton 胜 fixed，说明跨轮继续搜索机制有效；但明显负 ordinary 和 union。治理消耗 541,751 LLM token，而 scientific score 仍不如零 token 的 ordinary PySR。

### 工程改进与审计缺陷

- 短哈希 IPC 路径解决 Windows 长路径启动失败；
- requested 与 engine-measured evaluations 开始分开记录；
- orphan reservation 可以原位结算为 failed；
- 最终 Promotion scientific decision 有效，但未正常调用 `finish`，所以试点不是完整闭环。

v3 证明 warm-start 是必要基础，却反证了“继续增加 LLM token 就能改善治理质量”。

## 7. v4：binding controller 与零 LLM pilot

### 设计变化

v4 将最终执行权收回确定性 controller：

- LLM 权限降为受限结构假设；
- controller 负责预算、seed、动作、候选保留、回滚和 Promotion；
- 增加结构诊断、分区 evidence memory 和 offline policy replay；
- 修复 Promotion 过早退出；
- 在新 manifest 中冻结 3 个 paired seeds。

试点使用 `static_s01`，seeds 8201–8203，每个 arm/seed 请求 3,000 evaluations，总计 36,000。

### 结果

| seed | Hamilton | ordinary | fixed | union |
|---:|---:|---:|---:|---:|
| 8201 | 0.098971 | 0.098971 | 0.098971 | 0.194164 |
| 8202 | **0.137795** | 0.178332 | 0.178332 | 0.078456 |
| 8203 | **0.011305** | 0.017829 | 0.017829 | 0.453868 |

- 对 ordinary：2 胜 1 平；
- 对 fixed：2 胜 1 平；
- 对 union：2 胜 1 负；
- Hamilton 相对 fixed 的平均 engine-measured evaluations 少约 9.8%。

但所有 binding action 均为 `initialize/continue`，LLM token 为 0。提升来自 persistent warm-state 和确定性治理，而不是 LLM。seed 8203 得到近似式 `0.49999532*x1*x2**2`，但仍未通过 `1e-8` 的严格真值阈值。

v4 是 controller/warm-state 的正向证据，也是研究目标发生偏移的转折点：系统更稳定、更便宜，但已经没有 LLM 因果路径。

## 8. v5：压缩 planner 与完整 evidence-memory 链路

### 设计变化

v5 恢复每轮一次真实 LLM 调用，同时保留 binding controller 的最终执行权：

1. controller 根据冻结 policy 决定并执行当前轮；
2. PySR 完成搜索并产生聚合诊断；
3. `deepseek-v4-flash` 接收脱敏的压缩 payload；
4. proposal 经白名单 validator 后作为 weak hypothesis 写入 memory；
5. proposal 不得直接修改配置、预算、Promotion 或已执行动作。

试点更换为 `static_s02`，使用 seeds 8301–8303，每个 arm/seed 请求 4,500 evaluations，总正式预算 54,000。

### 结果

| seed | Hamilton | ordinary | fixed | union |
|---:|---:|---:|---:|---:|
| 8301 | 0.453598 | **0.418498** | 0.453598 | 0.487998 |
| 8302 | **0.459983** | 0.679757 | 0.679757 | 0.642576 |
| 8303 | **0.163986** | 0.245375 | 0.245375 | 0.672604 |

- 对 ordinary：2 胜 1 负；
- 对 fixed：2 胜 1 平；
- 对 union：3 胜 0 负；
- 9/9 planner calls 成功；
- 9/9 rounds 写入 evidence memory；
- LLM token：5,120，保守 cache-miss 费用约 ¥0.006466；
- 三个最佳式均未通过严格 ground-truth equivalence。

### 解释

v5 的 token 很少本身不是问题；真正的问题是 planner 没有进入性能因果链。全部 binding action 仍是 `initialize/continue`，planner proposal 没有改变下一轮搜索配置或预算。因此 v5 的正向成绩仍主要来自 warm-start 和 controller。

此外，Hamilton 平均 engine-measured evaluations 为 7,905，ordinary 为 5,179，Hamilton 对 ordinary 的结果存在计算量混杂；相对 fixed 的 2 胜 1 平更能支持 warm-state continuation。

运行中 union/seed 8302 因外壳超时后的残留子进程被重复执行一次，额外产生 1,500 requested evaluations。正式配对仍只使用冻结的 54,000 结果；实际 ledger 总量为 55,500，偏差已单独披露。

## 9. 架构演化

| 能力 | v1 | v2 | v3 | v4 | v5 |
|---|---|---|---|---|---|
| PySR 跨轮状态 | 否 | 否 | 是 | 是 | 是 |
| `continue` 动作 | 弱/不稳定 | 否 | 是 | 是 | 是 |
| Binding controller | 否 | 部分 | 部分 | 是 | 是 |
| LLM 真正可改变搜索 | 是 | 是 | 是 | 否 | 否，仅 advisory |
| Engine-measured evaluations | 否 | 是 | 是 | 是 | 是 |
| 严格真值审计 | 否 | 初步 | 是 | 是 | 是 |
| 每轮 evidence memory | 自由文本 | 自由文本 | L2 | controller 分区 | strong/weak 每轮落盘 |
| Planner token 约束 | 很弱 | 很弱 | 仍高 | 不调用 | 单次压缩调用 |
| 运行闭环可靠性 | 低 | 中 | 中 | 高 | 高 |

整体变化可以概括为：

```text
自由 LLM Agent 控制
  → 加入公平基线与诊断
  → 修复 PySR 状态连续性
  → controller 收回执行权
  → 恢复低成本 advisory planner
```

可靠性沿这条路径提高，但 LLM 的实际控制力同时下降。v6 必须在安全性与因果影响之间建立新的中间层，而不能简单回到 v1 的高自由度模式。

## 10. Token 演化

| 版本 | Hamilton LLM token | 说明 |
|---|---:|---|
| v1 | 2,751,149 | 3 个任务，含恢复与无效尝试开销 |
| v2 | 1,402,011 | 2 个任务，各 1 repeat |
| v3 | 541,751 | 1 个任务、1 seed，仍高于收益 |
| v4 | 0 | controller-only pilot，不是完整 LLM Hamilton |
| v5 | 5,120 | 3 seeds、9 calls，压缩 JSON planner |

v5 相对 v3 即使覆盖 3 个 seeds，总 token 仍减少约 99.06%。这证明压缩 planner 的成本问题已基本解决，但没有证明 planner 的决策价值。

## 11. 当前已证明和未证明的事实

### 已证明

- Hamilton 可以可靠保持 PySR 的跨轮搜索状态；
- binding controller 可以在 LLM 之外确定性执行预算、保留和回滚；
- 每轮 LLM proposal 与 evidence memory 可以低成本、可审计地落盘；
- warm-state 在多个 seed 上可以优于相同 seed 的独立 fixed restart；
- 扩大算子集合并不必然改善结果；
- 高 token 自由对话不是治理质量的充分条件。

### 尚未证明

- LLM Hamilton 在相同 engine-measured evaluations 下稳定优于 persistent PySR；
- LLM policy 稳定优于纯规则 controller；
- LLM 对 static、dynamic 和其他任务具有一致的有效干预策略；
- Hamilton 能以高于 PySR 的概率严格恢复真实公式；
- 当前 gains 可以跨任务、跨 seed 和确认集复现。

## 12. 对最初研究目标的判断

最初目标是利用 LLM 的结构推理、残差解释和历史记忆改善 PySR。v1 曾提供一个值得复验的方向：LLM 根据动态残差扩大到 `tanh` 后取得明显改善。但后续版本主要围绕运行稳定性和成本优化，逐渐让 controller 取代了 LLM 的执行作用。

因此，v4/v5 不是研究失败，而是完成了必要的实验基础设施；但如果下一阶段继续只优化 controller、warm-start 和审计，而不给 LLM 一个受控且真实的动作空间，就会偏离原始研究问题。

## 13. 建议的下一阶段：LLM 因果消融

下一代实验应将“LLM 是否提升 PySR”设为唯一主要问题，并冻结三个核心实验臂：

| 实验臂 | Persistent warm-start | Controller | LLM 可改变搜索 |
|---|---:|---:|---:|
| A：Persistent PySR | 是 | 仅预算与安全 | 否 |
| B：Rule Hamilton | 是 | 规则 intervention | 否 |
| C：LLM Hamilton | 是 | 审核 LLM intervention | 是 |

LLM 只能从预注册白名单中选择一个原子动作，例如：

- 保持配置继续搜索；
- 在允许集合中增加或移除一个算子；
- 在冻结区间内调整一次 parsimony；
- 选择 warm continuation 或显式 restart；
- 指定一个需要下一轮证伪的变量/算子结构假设。

controller 继续负责合法性、单变量变更、预算、回滚和最终提交。C 相对 A 的差异测量 LLM 总增益，C 相对 B 的差异测量 LLM 相对规则策略的增益。

最低实验要求：

1. 使用至少 2–3 个公开开发任务，包括一个能稳定触发结构 intervention 的任务；
2. 至少 10 个 paired seeds；
3. 同时匹配 requested 与 engine-measured evaluations；
4. 冻结 wall-clock 和失败重试策略；
5. 记录每个 LLM action 的批准、拒绝、执行、回滚及后续分数变化；
6. 设置 planner-off 消融，不能只比较 ordinary cold search；
7. 开始实验前定义“LLM 成功”：C 在多数 seed 上胜 A/B，且增益不能仅由更多计算解释。

如果 C 不能稳定胜 A 和 B，应诚实得出“当前 LLM 干预策略没有增量价值”，而不是继续增加 token 或自由度。

## 14. 证据索引

- v1：[运行门报告](../../experiments/hamilton_vs_pysr_governed_search/OPERATIONAL_GATE_STATUS_2026-07-28.md)
- v2：[operational gate 结果](../../experiments/hamilton_vs_pysr_governed_search_v2/RESULTS.zh-CN.md)
- v3：[四臂 pilot 结果](../../experiments/hamilton_vs_pysr_governed_search_v3/PILOT_RESULTS.zh-CN.md)
- v3：[机器可读证据](../../experiments/hamilton_vs_pysr_governed_search_v3/pilot_evidence.json)
- v4：[三 seed pilot 结果](../../experiments/hamilton_vs_pysr_governed_search_v4/PILOT_RESULTS.zh-CN.md)
- v4：[机器可读证据](../../experiments/hamilton_vs_pysr_governed_search_v4/pilot_evidence.json)
- v5：[完整链路 pilot 结果](../../experiments/hamilton_vs_pysr_governed_search_v5/PILOT_RESULTS.zh-CN.md)
- v5：[机器可读证据](../../experiments/hamilton_vs_pysr_governed_search_v5/pilot_evidence.json)
- v5：[真值审计](../../experiments/hamilton_vs_pysr_governed_search_v5/ground_truth_audit.json)
