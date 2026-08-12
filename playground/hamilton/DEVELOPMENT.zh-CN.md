# Hamilton 协作开发指南

本文定义 Hamilton 支持的入口和职责边界。修改编排、提示词、实验治理或 runner schema 前
必须阅读。英文原文见 [`DEVELOPMENT.md`](DEVELOPMENT.md)。

## 从这里开始

1. 阅读 [`../../docs/sragent/RESEARCH_PROTOCOL.zh-CN.md`](../../docs/sragent/RESEARCH_PROTOCOL.zh-CN.md)。
2. 阅读 [`README.md`](README.md)，了解运行时架构。
3. 阅读 [`TODO.md`](TODO.md)，了解已完成和待推进的研究工作。
4. 当前开发只使用 [`../../configs/hamilton/config.yaml`](../../configs/hamilton/config.yaml)。
5. 正式实验必须新建具名配置，绝不能改作冻结历史配置。

## 目录职责

| 路径 | 职责 |
|---|---|
| `playground/hamilton/core/` | 多轮 controller、Promotion、closure、OOD 和搜索控制逻辑 |
| `playground/hamilton/prompts/` | 所有 Hamilton 运行时提示词的唯一事实来源 |
| `playground/hamilton/workspace/` | 复制到运行 workspace 的干净公开模板 |
| `configs/hamilton/` | 运行配置目录和小型复现输入 |
| `evomaster/skills/run-sr-experiment/` | 确定性 SR runner 及其机器可读契约 |
| `docs/sragent/` | 协议、当前交接、实验规范和历史审计 |
| `runs/` | 生成证据；通常被忽略，绝不作为源代码 |

Private test/OOD 资产必须位于 Agent workspace 外的
`playground/hamilton/benchmarks/<name>/private/`，保持 Git 忽略且不得提交。

## 配置规则

- `config.yaml` 是唯一支持的集成开发入口。
- `config_no_pysr.yaml` 只检查协议管线，不是科学基线。
- 其他 `config_*.yaml` 是早期 smoke、长跑或恢复流程的冻结记录。部分含有与 workspace
  绑定的恢复状态，不具可移植性。
- 正式实验需要新的描述性配置、冻结总预算、位于 `docs/sragent/` 的任务规范以及新的
  run 目录。
- 凭据只能通过 `HAMILTON_API_KEY` 提供；禁止提交明文密钥。

Hamilton 配置中的相对提示词路径统一解析到 `playground/hamilton/prompts/`。不要在
`configs/` 下建立第二套提示词目录。

## Controller 边界

LLM 根据 L2 记忆为下一轮提出一个机器可读 PySR 配置。确定性 controller 始终负责：

- schema 和路径验证；
- 累计 evaluation 记账和动态额度；
- trust-region 检查、incumbent 持久化与回滚；
- 结果冻结和 Promotion 恢复；
- 搜索晋升门与最终科学成功门的区分；
- residual/OOD 证据释放和 closure 审计。

LLM 可以解释已释放的证据并形成可证伪的下一轮契约，但不能绕过这些 controller 检查。

## 变更流程

每次变更应保持聚焦，并更新距离最近的契约：

- controller 行为：在 `playground/hamilton/core/` 增加或更新针对性测试；
- runner schema：同步更新 runner 参考和契约测试；
- prompt 行为：更新运行时提示词和受影响的 closure 测试；
- 实验协议：更新 `docs/sragent/RESEARCH_PROTOCOL.md`，必要时新建任务规范。

提交前运行离线 Hamilton 测试：

```powershell
python -m unittest playground.hamilton.core.test_config_catalog `
  playground.hamilton.core.test_pysr_preflight `
  playground.hamilton.core.test_standard_runner
```

这些测试不得调用 DeepSeek、运行 PySR/Julia 或访问 private test/OOD 数据。分享提交前，
检查 `git status -sb` 和 `git diff --check`，只暂存预期文件，并将生成证据与实现变更分开。
