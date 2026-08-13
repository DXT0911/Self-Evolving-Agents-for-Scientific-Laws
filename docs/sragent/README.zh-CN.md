# SR Agent 文档索引

本目录中的文档承担不同职责。带日期的实验任务或审计只描述一次运行的证据，不能替代
当前运行时契约。

英文原文见 [`README.md`](README.md)。

## 当前契约

- [`REPOSITORY_MAP.zh-CN.md`](REPOSITORY_MAP.zh-CN.md)：仓库结构、职责和生成物导航。
- [`RESEARCH_PROTOCOL.zh-CN.md`](RESEARCH_PROTOCOL.zh-CN.md)：研究与 benchmark 隔离协议中文版。
- [`RESEARCH_PROTOCOL.md`](RESEARCH_PROTOCOL.md)：权威英文协议。
- [`../../playground/hamilton/DEVELOPMENT.zh-CN.md`](../../playground/hamilton/DEVELOPMENT.zh-CN.md)：协作开发指南。
- [`../../playground/hamilton/README.md`](../../playground/hamilton/README.md)：Hamilton 架构与运行行为。
- [`../../playground/hamilton/TODO.md`](../../playground/hamilton/TODO.md)：实现与研究待办。

## 当前实验依据

- [`../../experiments/README.zh-CN.md`](../../experiments/README.zh-CN.md)：版本化实验状态索引。
- [`../../experiments/hamilton_vs_pysr_governed_search/`](../../experiments/hamilton_vs_pysr_governed_search/)：
  governed Hamilton 与 PySR 的公开对照。三个任务、一个重复的运行门已经完成；计划中的
  正式多重复研究尚未运行。

实验协议、manifest、adapter 和紧凑报告放在 `experiments/`。完整 workspace、日志、
checkpoint 和重复数据副本只保留在本地并由 Git 忽略。

## 带日期的交接与总结

文件名中含日期的文档是时间点快照。恢复实验时可以阅读最新适用的交接，但必须用 Git
历史、配置和运行证据复核其中的结论。

未跟踪草稿只有在明确审阅并提交后，才属于本索引或仓库契约。

## 历史实验规范

以下文件保留早期验收、smoke、recovery 和 controlled-run 流程：

- `ADAPTIVE_MULTI_ROUND_TASK.md`
- `CONTROLLED_LONG_RUN_TASK.md`
- `LOW_BUDGET_SMOKE_TASK.md`
- `RESIDUAL_FEEDBACK_BLIND_8ROUND_TASK.md`
- `SINGLE_ROUND_CLOSURE_TASK.md`
- `SINGLE_ROUND_SCIENTIFIC_TASK.md`

不要把它们当作默认启动说明。对应配置可能依赖特定运行 workspace 或历史预算。
