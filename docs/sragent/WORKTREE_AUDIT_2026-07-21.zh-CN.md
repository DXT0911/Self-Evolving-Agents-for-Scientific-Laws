# Hamilton 工作区变更审计与固化计划

> 审计日期：2026-07-21
> 分支：`sragent/summer-2026`
> 审计基线：`040c0d1f182222d3417c0ba27913a62282924a2b`

## 结论

审计开始时 `git status` 有 57 个顶层状态条目：26 个修改、8 个删除、23 个未跟踪条目。
展开未跟踪目录后，共涉及 64 个实际文件。另有 7 个路径只有换行符/文件状态噪声，没有内容
diff，不应进入提交。

现有改动形成了可审查的研究原型，但还不是经过正式多轮实验验证的成品。固化目标是保存
基础设施、合约测试、协议和历史配置，同时排除凭证、私有 benchmark、完整 run workspace
及会向 Agent 注入搜索模板的 workspace 临时文件。

## 安全审计

- 原 57 项变更中未发现新加入的明文 API key；Hamilton 配置使用 `${HAMILTON_API_KEY}`。
- 对完整当前树复核时，额外发现未包含在原 57 项变更中的 `examples/llm/config.yaml` 也含有
  基线遗留凭证，已改为 `${OPENAI_API_KEY}` 和 `${ANTHROPIC_API_KEY}`。
- 基线历史曾包含旧凭证。本次提交只能从当前树删除它们，不能清除既有 Git 历史；所有旧
  凭证必须保持服务端撤销状态。
- 5 个训练 CSV 保留在公开 `workspace/input/`。
- 5 个 held-out test CSV 和 3 个最终 OOD CSV 从公开 workspace 删除，已迁移到被 Git 忽略的
  `playground/hamilton/benchmarks/viv/private/`，不得提交。
- 默认 Hamilton 配置不再向 LLM 暴露 `execute_bash`，editor 同时执行 workspace 边界与
  `.csv/.tsv/.parquet/.feather` 屏蔽。
- 低预算 smoke JSON 从 workspace 模板移至 `configs/hamilton/experiments/`，避免自动 seed
  到 Agent workspace。

## 文件级处置清单

### 1. 安全隔离与文献先验：保留

- `.gitignore`
- `configs/hamilton/config.yaml`
- `configs/hamilton/config_no_pysr.yaml`
- `evomaster/agent/session/base.py`
- `evomaster/agent/tools/base.py`
- `evomaster/agent/tools/builtin/__init__.py`
- `evomaster/agent/tools/builtin/editor.py`
- `evomaster/agent/tools/builtin/literature.py`
- `evomaster/skills/literature-grounding/SKILL.md`
- `evomaster/skills/literature-grounding/agents/openai.yaml`
- `playground/hamilton/workspace/task.md`
- 删除 `playground/hamilton/workspace/input/U000_free_vibration.csv`
- 删除 `playground/hamilton/workspace/input/U216_below_lockin.csv`
- 删除 `playground/hamilton/workspace/input/U248_test.csv`
- 删除 `playground/hamilton/workspace/input/U254_test.csv`
- 删除 `playground/hamilton/workspace/input/U260_test.csv`
- 删除 `playground/hamilton/workspace/input/U273_test.csv`
- 删除 `playground/hamilton/workspace/input/U282_test.csv`
- 删除 `playground/hamilton/workspace/input/U300_above_lockin.csv`

### 2. 标准 runner 与验证：保留

- `evomaster/core/playground.py` 中的 `use_skill` 可达性修复
- `evomaster/skills/run-sr-experiment/SKILL.md`
- `evomaster/skills/run-sr-experiment/agents/openai.yaml`
- `evomaster/skills/run-sr-experiment/references/adaptive_rounds.md`
- `evomaster/skills/run-sr-experiment/references/config_schema.md`
- `evomaster/skills/run-sr-experiment/references/ood_protocol.md`
- `evomaster/skills/run-sr-experiment/references/scientific_governance.md`
- `evomaster/skills/run-sr-experiment/scripts/run_experiment.py`
- `configs/hamilton/experiments/viv_u248_smoke.json`
- `run.py` 的 Windows UTF-8 输出修复

### 3. 闭环治理与预算：保留

- `evomaster/agent/agent.py`
- `playground/hamilton/core/exp.py`
- `playground/hamilton/core/playground.py`
- `configs/hamilton/prompts/hamilton_system.txt`
- `playground/hamilton/prompts/hamilton_system.txt`

### 4. OOD 与 preflight：保留

- `playground/hamilton/core/ood_evaluator.py`
- `playground/hamilton/core/pysr_preflight.py`
- `playground/hamilton/core/test_pysr_preflight.py`
- `playground/hamilton/core/test_standard_runner.py`

测试文件同时覆盖 runner、closure、governance、安全、文献先验和 OOD。为避免拆散共享 fixture，
统一放在功能提交之后的合约测试提交中。

### 5. 历史实验与恢复资产：保留但明确标记为非正式配置

- `configs/hamilton/config_adaptive.yaml`
- `configs/hamilton/config_controlled_long.yaml`
- `configs/hamilton/config_low_budget.yaml`
- `configs/hamilton/config_multiround_test.yaml`
- `configs/hamilton/config_promotion_resume.yaml`
- `configs/hamilton/multiround_test_task.md`
- `configs/hamilton/prompts/hamilton_adaptive_system.txt`
- `configs/hamilton/prompts/hamilton_adaptive_user.txt`
- `configs/hamilton/prompts/hamilton_promotion_resume_system.txt`
- `playground/hamilton/prompts/hamilton_adaptive_system.txt`
- `playground/hamilton/prompts/hamilton_adaptive_user.txt`
- `playground/hamilton/prompts/hamilton_promotion_resume_system.txt`

这些配置中的 `start_round`、`resume_completed_result` 和历史预算依赖特定 run workspace，不能
从干净模板直接运行。其状态集中记录在 `configs/hamilton/README.md`。

### 6. 文档与研究记录：保留并统一口径

- `README.md`、`README-zh.md`
- `WORKSPACE.md`、`WORKSPACE.zh-CN.md`
- `configs/hamilton/README.md`
- `playground/hamilton/README.md`、`playground/hamilton/TODO.md`
- `docs/sragent/ADAPTIVE_MULTI_ROUND_TASK.md`
- `docs/sragent/CONTROLLED_LONG_RUN_TASK.md`
- `docs/sragent/HAMILTON_PROGRESS_2026-07-21.zh-CN.md`
- `docs/sragent/LOW_BUDGET_SMOKE_TASK.md`
- `docs/sragent/RESEARCH_PROTOCOL.md`
- `docs/sragent/RESEARCH_PROTOCOL.zh-CN.md`
- `docs/sragent/SINGLE_ROUND_CLOSURE_TASK.md`
- `docs/sragent/SINGLE_ROUND_SCIENTIFIC_TASK.md`
- 本审计文件

### 7. 不提交的状态噪声

以下路径在审计开始时显示修改，但 `git diff` 无内容变化：

- `CLAUDE.md`
- `design.md`
- `findings.md`
- `playground/README.md`
- `playground/README_CN.md`
- `progress.md`
- `task_plan.md`

## 验证结果

- 44 项 `unittest` 合约测试通过；测试未调用 DeepSeek，PySR preflight 子进程被 mock，未运行
  PySR 搜索。
- 15 个相关 Python 文件通过 AST 语法解析。
- 7 个 Hamilton YAML 配置和 smoke JSON 通过解析。
- `git diff --check` 未发现空白错误；Windows 工作区存在预期的 LF/CRLF 提示。

## 提交顺序

建议并实际采用以下依赖顺序：

1. `feat(sragent): isolate benchmark data and add literature grounding`
2. `feat(sragent): add standardized SR experiment runner`
3. `feat(sragent): enforce Hamilton round governance and budgets`
4. `feat(sragent): add private OOD evaluation and PySR preflight`
5. `test(sragent): add runner and governance contract coverage`
6. `docs(sragent): consolidate Hamilton research status and run records`
7. `fix(security): remove credentials from LLM example config`

不 push、不改写基线历史，也不提交 `runs/`、`.env` 或私有 benchmark 目录。
