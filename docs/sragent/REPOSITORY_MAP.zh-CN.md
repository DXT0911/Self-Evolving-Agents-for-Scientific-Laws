# SR Agent 仓库地图

本地图回答一个问题：协作者应该到哪里阅读或修改？它只负责导航，不能替代下方链接的
运行时契约和研究协议。

英文原文见 [`REPOSITORY_MAP.md`](REPOSITORY_MAP.md)。

## 权威入口

| 需求 | 权威路径 |
|---|---|
| Fork 与分支工作流 | [`../../WORKSPACE.zh-CN.md`](../../WORKSPACE.zh-CN.md) |
| Hamilton 架构与使用 | [`../../playground/hamilton/README.md`](../../playground/hamilton/README.md) |
| Hamilton 开发流程 | [`../../playground/hamilton/DEVELOPMENT.zh-CN.md`](../../playground/hamilton/DEVELOPMENT.zh-CN.md) |
| 当前实现待办 | [`../../playground/hamilton/TODO.md`](../../playground/hamilton/TODO.md) |
| 科学与隔离协议 | [`RESEARCH_PROTOCOL.zh-CN.md`](RESEARCH_PROTOCOL.zh-CN.md) |
| 当前开发配置 | [`../../configs/hamilton/config.yaml`](../../configs/hamilton/config.yaml) |
| 配置生命周期与历史 | [`../../configs/hamilton/README.zh-CN.md`](../../configs/hamilton/README.zh-CN.md) |
| 版本化实验索引 | [`../../experiments/README.zh-CN.md`](../../experiments/README.zh-CN.md) |
| Governed-Hamilton 对照实验 | [`../../experiments/hamilton_vs_pysr_governed_search/README.zh-CN.md`](../../experiments/hamilton_vs_pysr_governed_search/README.zh-CN.md) |

## 目录职责

```text
Self-Evolving-Agents-for-Scientific-Laws/
├── evomaster/                 可复用上游 Agent 框架与 SR skills
├── playground/hamilton/       Hamilton controller、提示词、测试和公开模板
├── configs/hamilton/          当前、诊断、冻结历史和实验配置
├── docs/sragent/              当前研究契约和带日期历史快照
├── experiments/               版本化实验协议、adapter、测试和报告
├── runs/                      被忽略的运行证据；绝不是源代码
├── paper/                     继承的论文、数据、notebook 和复现资产
├── WORKSPACE*.md              fork、remote、分支和协作导航
└── README*.md                 继承的 EvoMaster 项目概览
```

`evomaster/`、`examples/` 和 `docs/` 下的一般文档继承自上游。只有确有需要且有针对性测试
覆盖时，才应修改 Hamilton 相关的框架部分。

## Hamilton 资产类别

| 类别 | 位置 | 规则 |
|---|---|---|
| Controller 实现 | `playground/hamilton/core/` | 可复用源码；行为变更必须有测试 |
| 运行时提示词 | `playground/hamilton/prompts/` | 唯一提示词事实来源 |
| 公开运行模板 | `playground/hamilton/workspace/` | 只版本化任务和公开训练输入 |
| 当前配置 | `configs/hamilton/config.yaml` | 唯一集成开发入口 |
| 诊断配置 | `configs/hamilton/config_no_pysr.yaml` | 仅检查协议管线；不是科学基线 |
| 历史配置 | 其他已记录的 `config_*.yaml` | 冻结背景；不要复用或静默修改 |
| 正式实验配置 | 与实验 manifest 关联的描述性配置 | 每个实验单独授权并冻结 |
| 研究协议 | `docs/sragent/RESEARCH_PROTOCOL.md` | 权威科学和隔离规则 |
| 带日期报告 | `docs/sragent/` 或实验目录中的带日期文件 | 历史证据，不是当前运行契约 |

根目录的 `task_plan.md`、`progress.md`、`findings.md` 和 `design.md` 是继承或历史项目笔记，
不是 Hamilton 运行时 L2 记忆。运行时 L2 记忆在每个运行 workspace 内创建，文件名为
`plan.md` 和 `findings.md`。

## 生成物和大型资产

生成证据与版本化源码明确分离：

- `runs/` 保存完整本地运行 workspace 和日志，并由 Git 忽略；
- 实验内的 `data_cache/`、`prepared_data/` 和 `launch_bundle/` 由 Git 忽略；
- Python、Julia、PySR、checkpoint 和模型缓存由根目录规则忽略；
- 紧凑报告、manifest、哈希、schema 和最终图表可以版本化；
- controller 私有 test/OOD 资产位于 Agent workspace 外并保持忽略。

整理仓库时不要删除本地证据。只有在单独明确授权的资产管理任务中，才能归档或移除它们。

## 安全变更规则

优先增加索引或修复链接，不要移动冻结配置、带日期报告或实验资产。路径迁移必须同步更新
import、manifest、哈希、文档和测试，并作为单独的兼容性变更处理。
