# SR Agent 研究规范

[English](./RESEARCH_PROTOCOL.md) | [简体中文](./RESEARCH_PROTOCOL.zh-CN.md)

## 研究范围

研究目标是构建一个通用的 SR Agent，使其能够：

1. 检查数据及任务元信息；
2. 配置符号回归搜索；
3. 调用数值符号回归引擎执行搜索；
4. 使用针对具体任务设计的验证器评估候选方程；
5. 诊断失败原因，并据此调整下一轮搜索；
6. 在不同轮次和不同任务之间保存并复用有效策略。

VIV（涡激振动）是当前用于深入验证的案例，但它不等同于通用框架本身。后续还应使用合成系统和标准基准任务来检验框架的广泛适用性。

## 当前两周的研究重点

核心问题：

> 与只关注拟合误差的反馈相比，考虑动力学性质的验证器反馈，能否帮助 SR Agent 选出更准确地复现长期非线性动力学行为的方程？

初步对比实验：

1. 直接运行 PySR；
2. 只使用拟合反馈的 Hamilton；
3. 同时使用拟合反馈和轨迹反馈的 Hamilton；
4. 可选：加入逐项消融反馈的 Hamilton。

## VIV 数据使用规范

Agent 的公开 workspace 只包含训练输入：

`playground/hamilton/workspace/input/`

公开训练文件：

- `U248_train.csv`
- `U254_train.csv`
- `U260_train.csv`
- `U273_train.csv`
- `U282_train.csv`

controller 私有 benchmark 资产位于 Agent workspace 外、被 Git 忽略的
`playground/hamilton/benchmarks/viv/private/`。这些文件不得复制到 run workspace，也不得
提交到 Git；私有 manifest 负责记录用途和完整性元数据。

留出的测试集（controller 私有）：

- `U248_test.csv`
- `U254_test.csv`
- `U260_test.csv`
- `U273_test.csv`
- `U282_test.csv`

仅用于最终的分布外（OOD）评估（controller 私有）：

- `U000_free_vibration.csv`
- `U216_below_lockin.csv`
- `U300_above_lockin.csv`

不得利用测试集或 OOD 评估结果来选择运算符、方程模板、复杂度上限、超参数、提示词或候选方程。

controller 只能按 OOD 协议释放相应层级允许的紧凑摘要。私有原始数据行、未经批准的文件名、
目标标签和参考方程均不得提供给 Agent。

进行内部验证时，应按连续时间区间划分训练轨迹，不要随机划分数据行，因为相邻时刻的样本之间具有很强的相关性。

## 验证器必须输出的内容

每个候选方程都应生成一条机器可读的记录，其中包含：

- 原始方程和化简后的方程；
- 方程项列表及复杂度；
- 训练集和内部验证集上的逐点指标；
- 数值积分是否成功；若失败，还要记录失败原因；
- 稳态振幅误差；
- 振荡频率误差；
- 从零初始状态到稳定状态的定性行为；
- 从大初始状态到稳定状态的定性行为；
- 两种初始条件所得吸引子之间的一致程度；
- 不同风速下方程结构的一致性；
- 运行时间、搜索评估次数、随机种子、模型名称和 Git 提交版本。

## 实验产物管理规范

应提交到 Git：

- 源代码；
- 体积较小的配置文件；
- JSON/CSV 格式的精简结果摘要；
- 报告中使用的最终图表；
- 环境和版本清单；
- 文档及实验规范。

应保留在本地或外部实验产物存储中：

- 完整的运行工作区；
- 完整轨迹和详细的 LLM 日志；
- PySR/Julia 缓存；
- 重复的数据副本；
- 临时图表；
- 体积较大的候选方程表。

每一个写入报告的实验，都必须能够通过以下信息复现：

```text
Git 提交版本
+ 配置
+ 数据版本
+ 随机种子
+ 环境版本
+ 模型及服务提供方标识
```

## Git 提交规范

示例：

```text
docs(sragent): document VIV data and evaluation protocol
test(sragent): add evaluator smoke tests
feat(sragent): add dynamics-aware trajectory verifier
exp(sragent): add direct PySR VIV baseline
exp(sragent): compare fit-only and dynamics-aware feedback
fix(sragent): prevent test trajectory leakage
```

这些提交信息可以理解为：

- `docs`：补充 SR Agent 文档；
- `test`：增加测试；
- `feat`：增加新功能；
- `exp`：增加或更新实验；
- `fix`：修复问题。

每当实现进度发生变化时，都要同步更新 `playground/hamilton/TODO.md`。
