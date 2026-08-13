# Hamilton vs PySR v2：Codex 协作者交接

## 你要继续的研究

目标不是让 LLM 直接猜方程，而是检验 Hamilton 能否根据确定性验证和残差证据，更有效地
控制下一轮 PySR 搜索。v2 排除 VIV，比较四个实验臂：连续 PySR、匹配重启 PySR、从第一轮
就拥有完整算子集合的 PySR，以及 governed Hamilton。

权威分支：`experiment/hamilton-pysr-v2`。旧 v1 证据位于
`experiments/hamilton_vs_pysr_governed_search/public_evidence/operational_gate_v1/`；v2 协议位于
`experiments/hamilton_vs_pysr_governed_search_v2/`。

截至 2026-08-14，v2 operational gate 的 8 个运行已经全部完成，禁止重复运行。先读
`experiments/hamilton_vs_pysr_governed_search_v2/RESULTS.zh-CN.md` 和
`public_evidence/operational_gate_v2/`。当前结果不支持“已经稳定胜过普通 PySR”，因此下一项
工作是开发 v3 搜索延续/保守动作策略，而不是打开 v2 sealed test。

## 从 GitHub 建立电脑环境

```powershell
git clone https://github.com/DXT0911/Self-Evolving-Agents-for-Scientific-Laws.git
cd Self-Evolving-Agents-for-Scientific-Laws
git switch experiment/hamilton-pysr-v2

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pysr==1.5.9 juliacall==0.9.26 numpy==2.3.2 pandas==2.3.3 sympy==1.14.0 PyYAML==6.0.3
```

DeepSeek 凭据只放在当前 PowerShell 会话或本机 `.env`，绝不能提交：

```powershell
$env:HAMILTON_API_KEY = "你的 DeepSeek API key"
```

获取固定公开数据并生成不透明输入：

```powershell
python -m experiments.hamilton_vs_pysr_governed_search.acquire_public_data
python -m experiments.hamilton_vs_pysr_governed_search.prepare_public_data `
  experiments/hamilton_vs_pysr_governed_search/pilot_manifest.yaml
```

先运行离线测试；此步骤不调用 DeepSeek、PySR 或 Julia：

```powershell
python -m unittest `
  experiments.hamilton_vs_pysr_governed_search.test_acquire_public_data `
  experiments.hamilton_vs_pysr_governed_search.test_export_public_evidence `
  experiments.hamilton_vs_pysr_governed_search.test_evaluation_curves `
  experiments.hamilton_vs_pysr_governed_search.test_ground_truth_equivalence `
  playground.hamilton.core.test_pysr_preflight `
  playground.hamilton.core.test_standard_runner
```

## 发给 Codex 的恢复提示词

把以下整段复制给你电脑上的 Codex：

> 请继续 Hamilton vs PySR v2 研究。仓库是当前目录，权威分支是
> `experiment/hamilton-pysr-v2`。开始时只检查 `git status -sb`、当前分支、remote 和最近
> 10 个提交，不要直接运行实验。完整阅读 `WORKSPACE.zh-CN.md`、
> `docs/sragent/RESEARCH_PROTOCOL.zh-CN.md`、`playground/hamilton/DEVELOPMENT.zh-CN.md`、
> `experiments/hamilton_vs_pysr_governed_search_v2/README.zh-CN.md`、`PROTOCOL.md`、
> `dataset_split.yaml`、`manifest.yaml`、`RESULTS.zh-CN.md`、v2
> `public_evidence/operational_gate_v2/README.md`，以及 v1
> `public_evidence/operational_gate_v1/README.md`。
> v2 排除 VIV；开发集是 static_s01/dynamic_d01，验证集和封存测试集以 dataset_split.yaml
> 为准。参考方程只能由 controller 使用，绝不能复制到 Agent workspace。四个实验臂必须
> 使用相同公开字节、划分、初始配置、总 evaluation 预算、evaluator 和配对 seed；Hamilton
> 先运行，随后只把额度和 seed 冻结给三个基线，不能复制方程、score、残差或 L2。
> 在任何联网或正式运行前，先报告离线测试、数据哈希、PySR/Julia preflight、manifest 和
> launch-bundle 审计。保留完整运行证据，不使用 git reset --hard、git clean 或强推，不提交
> API key、`.env`、原始运行目录、数据缓存、provider 日志或 private/OOD 资产。若当前状态
> 已有结果，先读取最近的版本化报告和机器账本再继续，绝不能重复已完成的 PySR episode。
> v2 operational gate 已完成且显示 mixed result；不要打开 sealed test。先提出并测试一种能
> 延续 PySR search state、允许“保持配置继续搜索”且对 ordinary PySR 公平的 v3 设计。

## 协作与提交规则

- 每次拉取后先检查 Git commit 与 `environment.lock.yaml`；
- controller/runner 行为变更必须有针对性单元测试；
- 先在开发集修改，再在验证集选择一次最终策略；
- 测试集打开后禁止继续调整 v2；
- 完整 workspace 和日志保留本地，紧凑 JSON/报告进入 Git；
- 推送到自己的分支并通过 PR 合并，不覆盖他人的运行目录。

如果 Codex 发现 manifest、实际命令和报告不一致，应立即停止正式运行并先修复契约，不要用
人工解释绕过审计。
