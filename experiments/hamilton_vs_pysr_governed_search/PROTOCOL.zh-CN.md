# 预注册对照实验协议

英文原文见 [`PROTOCOL.md`](PROTOCOL.md)。如中英文解释出现差异，以冻结英文协议和机器可读
契约为准。

## 1. 研究问题

在公开数据、初始 PySR 搜索空间、累计 evaluations、候选评价方法和配对 seeds 一致时，
当前 governed Hamilton controller 相比固定 PySR 能否改善：

1. 终点验证质量；
2. 跨重复稳定性；
3. 单位累计 evaluation 下的 best-so-far 质量？

本实验不比较当前 controller 与旧版 Hamilton。

## 2. 假设

### 主要零假设

在累计 PySR evaluation 预算匹配时，governed Hamilton 在任务级终点验证质量和 anytime
效率上不优于 ordinary PySR。

### 次要零假设

- Governed Hamilton 不会降低跨重复离散程度或灾难性失败率。
- Governed Hamilton 不会提高隐藏真值任务上的精确/等价恢复率。
- Governed Hamilton 不会改善 VIV 公开连续尾段验证。

本公开数据实验的任何结果都不能证明 private/OOD 泛化或真实 VIV 物理定律。

## 3. 实验臂

### `ordinary_pysr`

- 进行一次不中断的 PySR 搜索。
- 使用任务对应的冻结配置。
- 只在配对 Hamilton 运行后启动，并获得 Hamilton 实际累计预算 `B_r`，其中 `B_r <= B`。
- 使用该重复的 primary seed。
- 不使用 LLM，不进行自适应配置变更。

### `fixed_schedule_pysr`

- 只在配对 Hamilton 预算轨迹冻结后运行。
- 精确重放 Hamilton 实际各 episode evaluation 额度和 seed bundle。
- 每个 episode 重启 PySR，但科学搜索配置保持固定。
- 不使用 LLM。

该实验臂用于区分搜索控制收益与重启或 seed 多样化收益。

### `governed_hamilton`

- 从相同初始 PySR 配置开始。
- 首先运行，在累计上限 `B` 内获得 controller 动态决定的 episode 额度。
- LLM 只能提出 controller 允许的搜索配置变更。
- incumbent 保留、trust region、rollback、累计账本、动态额度、证据记忆、Promotion 和
  closure 始终由确定性 controller 负责。

三个实验臂使用相同的确定性候选 evaluator。LLM 不能直接接受科学候选。

## 4. 公平性契约

每个任务及其配对重复中，以下内容必须一致：

- 公开数据集字节和数据指纹；
- 训练/验证划分；
- target 和 feature 列；
- 初始 PySR 变量、operators、复杂度上限、population 设置和 parsimony；
- 累计 PySR evaluations 总数；
- 候选表大小和 evaluator；
- 数值容差和科学 gates；
- 多 episode 实验臂使用的 seed bundle；
- 代码 commit、Python/PySR/Julia 版本和硬件分配。

Controller 管理的 `search.max_evals` 只能按照冻结动态分配规则在 Hamilton episode 间变化。
Hamilton 结束后，controller 导出只包含额度和 seeds 的 SHA-256 冻结轨迹。若实际总和
`B_r <= B`，ordinary PySR 连续获得 `B_r`，fixed-schedule PySR 重放相同 episode 额度。
候选方程、scores、残差和 L2 记忆绝不复制到任一基线。

LLM tokens 不换算成 PySR evaluations，必须单独报告。

## 5. 数据集家族

Pilot 计划包含 11 个任务：

- 6 个盲测、已知真值的静态符号回归任务；
- 4 个已知真值的动力学导数任务；
- 1 个公开 VIV 任务，初始为 U248。

外部任务精确标识必须在启动前冻结。静态和动力学真值可由 controller 查看，但不能复制到
Agent workspace。

VIV U248 只是一项真实数据任务，不能证明广泛普适性。其他公开风速在 pilot 协议稳定后
再用于扩展；聚合分析中应将它们视作一个相关 benchmark 家族。

## 6. 重复与 seeds

准备 manifest 定义三个配对 pilot 重复。每个重复包含：

- ordinary PySR 使用的一个 primary seed；
- fixed-schedule PySR 和 Hamilton 共享的三-seed episode bundle。

观察到第一个科学结果后不得修改 seed 计划。Pilot 验证运行与契约后，正式研究至少应使用
五个配对重复。

LLM 随机性通过 provider、model、temperature、可用的 request metadata 和运行时间戳
单独记录。除非 provider 保证，否则不得称其为完全 seeded。

## 7. 结果指标

### 通用主要指标

1. 在配对实际预算 `B_r` 下的终点公开验证 NRMSE。
2. 使用 0 到 1 的标准化累计 evaluation 比例，对 best-so-far 验证 score 曲线计算
   anytime area。
3. 运行成功指标：已完成、候选有限且 evaluator 输出有效。

NRMSE 和 anytime area 越低越好。精确 score 定义和插值网格必须在启动前冻结。

### 已知真值指标

- 确定性符号化简后的代数等价；
- controller-only challenge grid 上的数值等价；
- 所选变量 precision/recall；
- 所选表达式复杂度；
- 跨重复精确/等价恢复率。

隐藏方程和 challenge grid 不得进入 Agent 提示词或 workspace。

### 动力学导数指标

- 导数验证指标；
- 所选导数的代数等价和 controller challenge-grid 等价；
- 残差结构和表达式复杂度。

所选 ODE-Strogatz 任务每次只暴露一个导数分量。除非发现两个耦合方程并单独预注册联合系统
evaluator，否则不能据此声称轨迹或吸引子恢复。Pilot 中不能静默加入长期指标。

### VIV 指标

- 训练和连续尾段验证指标；
- 当前短期 ODE 轨迹指标；
- 所选方程复杂度和实际变量依赖；
- 残差诊断状态；
- 不包含 private/OOD 指标。

发现或未发现速度项只具有描述性，不是通用成功门。

### 资源指标

- 预留和消耗的 PySR evaluations；
- best-so-far score 与累计 evaluations 的关系；
- wall-clock 时间；
- Hamilton 的 LLM 输入/输出 tokens 和 Promotion 尝试次数；
- rejected、failed、interrupted、replayed 和 rolled-back episodes。

## 8. 统计分析

- 按任务和重复 seed 计划配对实验臂。
- 报告每个任务结果，不能只报告聚合赢家。
- 连续结果报告中位数、四分位距、配对差异和跨任务 bootstrap 置信区间。
- 已知真值恢复报告计数和配对任务级比例。
- 将 VIV 各风速视为一个家族，而非独立重复。
- Pilot 结果与正式结果分开报告。
- 失败运行的缺失 score 不得被有利地省略；应用冻结失败惩罚并报告失败原因。

主要比较为 `governed_hamilton` 对 `ordinary_pysr`；`fixed_schedule_pysr` 是诊断基线。

## 9. 停止与适应

- Hamilton 在达到累计上限、三轮或结构化终止失败时停止。随后基线精确获得 Hamilton 已经
  预留的 evaluations。
- 只有相同确定性成功契约适用于所有实验臂时，科学成功才能让 Hamilton 提前停止。
- Hamilton 未使用的上限必须记录，且不分配给任何基线。
- 观察第一个结果后不得改变数据集选择、指标、gates 和 seed 计划。
- Pilot 发现只能促成新的版本化实验，不能原地重写既有实验。

## 10. 泄漏与安全

- 只使用公开训练数据。
- 不向 Hamilton 释放任何 private test/OOD 文件、文件名、原始行、参考方程或系数。
- 真值任务在 Agent workspace 中使用不透明任务标识。
- 数据 adapter 使用前生成指纹和紧凑 metadata。
- DeepSeek 与 PySR/Julia 始终分别授权。
- 准备状态 manifest 不能通过启动验证。
