# Hamilton 配置目录

[`config.yaml`](config.yaml) 是唯一权威开发入口。它启用 benchmark 隔离、文献先验、
标准 SR runner、科学治理和 controller 侧 PySR preflight，但尚不是冻结的正式实验配置。

`experiment.promotion.max_tokens` 限制独立的 `PromotionExp` Agent 运行，
`max_attempts` 限制恢复尝试次数。存在全局 token 预算时，Playground 会在启动
`RoundExp` 前预留 Promotion 配额。

所有 provider 凭据必须来自 `${HAMILTON_API_KEY}`，禁止提交明文密钥。

英文原文见 [`README.md`](README.md)。

## 支持的入口

| 文件 | 用途 | 状态 |
|---|---|---|
| `config.yaml` | 当前集成式 Hamilton 开发入口 | 权威开发配置 |
| `config_no_pysr.yaml` | 不运行 PySR 的 prompt/closure 调试 | 仅诊断；不是 benchmark |
| `config_governed_pysr_public_pilot.yaml` | 公开 Hamilton-vs-PySR pilot 的冻结 governed-Hamilton 实验臂 | 需授权的正式 pilot |

`config_no_pysr.yaml` 只会产生带标签的协议调试产物，不能用于确认候选方程、
benchmark 性能或科学成功。

`config_governed_pysr_public_pilot.yaml` 与
`experiments/hamilton_vs_pysr_governed_search/pilot_manifest.yaml` 绑定。只有在分别取得
DeepSeek 与 PySR/Julia 授权，且 manifest 通过启动验证后才能运行。

## 冻结历史配置

以下文件保存早期 smoke、adaptive、controlled-run 或 recovery 设置，使带日期的研究记录
仍可解释：

- `config_low_budget.yaml`
- `config_adaptive.yaml`
- `config_multiround_test.yaml`
- `config_controlled_long.yaml`
- `config_promotion_resume.yaml`
- `config_residual_blind_8round.yaml`

不要用它们启动新实验。部分文件包含与特定 workspace 绑定的
`resume_completed_result` 或 `start_round` 相对路径，其他文件则早于当前搜索控制契约。
正式实验必须使用新的描述性配置、明确验证过的 workspace 和冻结累计预算。

这些文件名和位置必须保持稳定：带日期的报告和本地证据可能直接引用它们。应通过本目录
索引进行整理，不要在缺少独立兼容性迁移评审时将其移动到新目录。

## 提示词位置

运行时提示词路径统一解析到 `playground/hamilton/prompts/`，该目录是唯一事实来源。
不要在 `configs/hamilton/` 下创建提示词副本。

## 实验 JSON 示例

`experiments/viv_u248_smoke.json` 是保留的低预算 runner 输入。它有意放在 workspace
模板之外，避免 Agent 运行被搜索模板预置。若需手工复现该 smoke 流程，应先把它复制到
一次性运行 workspace，再调用标准 runner。它不是科学成功证据。

目录职责、测试命令和新增正式实验的流程见
[`../../playground/hamilton/DEVELOPMENT.zh-CN.md`](../../playground/hamilton/DEVELOPMENT.zh-CN.md)。
