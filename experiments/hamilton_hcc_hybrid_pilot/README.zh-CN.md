# HCC 混合线路 Pilot — 协作者运行手册

本目录是「Hamilton（HCC LLM 闭环）对比普通 PySR」的符号回归 pilot 实验（已预注册、冻结执行前）。
本文档告诉协作者如何在本地搭建环境并跑完整实验。

- 冻结设计（机器可读）：[`pilot_manifest.yaml`](pilot_manifest.yaml)
- 预注册方案：`PRE_REGISTRATION.zh-CN.md`
- 交接文档：`docs/sragent/HCC_PILOT_HANDOFF_2026-08-18.zh-CN.md`
- 实验索引：`experiments/README.md`

## 实验是什么

研究问题：在相同公开数据、初始 PySR 搜索空间、累计 evaluation 预算、候选 evaluator 和配对
seed 计划下，治理式 LLM 搜索控制（H 臂）能否在**最终 incumbent 科学分数**上优于固定 PySR（B 臂）。

- 设计：2 任务（`static_s02`、`dynamic_d01`）× 3 seed（8401/8402/8403）× 2 臂
  （H = `hcc_llm`，B = `bare_pysr`）= 12 次运行。
- 每轮：独立冷启动 PySR（不继承上一轮进化种群），3 轮 × 1500 evals。
- 主判据：配对符号检验（`scientific_score` **越小越好**，H < B 记 H 胜）。
- 定位：`development_pilot_only_not_confirmatory`（开发性 pilot，非正式多重复验证研究）。

## 前置条件

- Python 3.10+（推荐 3.11/3.12）
- Julia（PySR 依赖，按 PySR 官方文档安装；仓库提供 `precompile_pysr.jl` 预热脚本）
- git
- DeepSeek API key（仅 H 臂需要，模型 `deepseek-v4-flash`；B 臂无 LLM 不调用）

## 1. 安装 Python 依赖

```bash
pip install -r requirements.txt
# 或 uv sync
```

安装 PySR（含 Julia 运行时）：

```bash
pip install pysr
python -c "import pysr; pysr.julia_helpers.init_julia()"   # 首次自动配置 Julia
```

> PySR/Julia 安装以 `evomaster/skills/pysr/SKILL.md` 与 PySR 官方文档为准。

## 2. 配置 API key

```bash
cp .env.template .env
# 编辑 .env，加入（Hamilton 所有 config 均引用 ${HAMILTON_API_KEY}）：
# HAMILTON_API_KEY=sk-xxxxxxxx
```

> B 臂（`bare_pysr`）不调用 LLM，无需 key；H 臂由
> `configs/hamilton/config_hcc_hybrid_pilot.yaml` 引用该变量。

## 3. 获取并准备公开数据

数据字节不入库（见 `experiments/hamilton_vs_pysr_governed_search/.gitignore`），从冻结的
PMLB revision 下载并校验 SHA-256：

```bash
# 下载原始 PMLB 输入到 data_cache/
python -m experiments.hamilton_vs_pysr_governed_search.acquire_public_data

# 生成不透明 CSV 到 prepared_data/{task}/input/data.csv
python -m experiments.hamilton_vs_pysr_governed_search.prepare_public_data \
  experiments/hamilton_vs_pysr_governed_search/pilot_manifest.yaml
```

## 4. 构建冻结运行 bundle

```bash
python experiments/hamilton_hcc_hybrid_pilot/build_pilot.py
```

生成 `run_bundle/`（12 个 cell 的 `task.md`、`data.csv`、`.hamilton_seed_plan.json`、
`.hamilton_bridge_policy.json`、`run_matrix.json`、`freeze_lock.json`），**不**执行 PySR/LLM。
`run_bundle/` 被 git 忽略，由本脚本确定性重建；build 会校验每个输入的 SHA-256。

## 5. 运行实验矩阵

先跑快速的 B 臂（无 LLM，可并行）：

```bash
python experiments/hamilton_hcc_hybrid_pilot/run_matrix.py --arm bare_pysr --workers 3
```

再跑 H 臂（LLM 闭环，建议串行以控制成本与限流）：

```bash
python experiments/hamilton_hcc_hybrid_pilot/run_matrix.py --arm hcc_llm --workers 1
```

可加筛选参数只跑子集，例如：

```bash
python experiments/hamilton_hcc_hybrid_pilot/run_matrix.py --arm hcc_llm \
  --task static_s02 --repeat repeat_1 --workers 1
```

> 每个 cell 的 stdout/stderr 写入 `<run_bundle>/<arm>/<task>/<repeat>/run.log`；
> 结果摘要写入 `run_matrix_results.json`（被 git 忽略）。

## 6. 收集结果

```bash
python experiments/hamilton_hcc_hybrid_pilot/collect_pilot.py
# 或 python experiments/hamilton_hcc_hybrid_pilot/run_matrix.py --collect
```

collect 读取 H 臂 `.hamilton_search_state.json` 的 `incumbent.score` 与 B 臂
`baseline_summary.json`，对 6 对（2 task × 3 seed）做配对符号检验，输出 H 是否优于 B。

## 7. 结果判读

- 主判据：final incumbent `scientific_score`（越小越好），配对比较 H < B。
- 次要：`val_r2`、`tokens_per_run`、`engine_measured_evaluations_alignment`、
  `closure_reliability`、`round1_config_compliance`。
- 本实验是 development pilot；如需验证性结论，须在观察新结果前冻结事后指标与容差。

### 本次运行结果（2026-08-18，12/12 cells）

主判据（配对符号检验）：**H 胜 2 / 负 0 / 平 4**，n=2，`p_two_sided = 0.5`（不显著）。

| 任务 / seed | H 臂 | B 臂 | 结果 |
|---|---|---|---|
| static_s02 / repeat_1 | 0.02419 | 0.02419 | 平 |
| static_s02 / repeat_2 | 0.02508 | 0.02508 | 平 |
| static_s02 / repeat_3 | **0.29924** | 0.35061 | **H 胜** |
| dynamic_d01 / repeat_1 | 0.73408 | 0.73408 | 平 |
| dynamic_d01 / repeat_2 | 0.82218 | 0.82218 | 平（stale，见注意事项） |
| dynamic_d01 / repeat_3 | **0.60685** | 0.75157 | **H 胜** |

- H 臂从不劣于 B 臂（0 负）；2 个 seed 严格更优，4 个平局。
- Round-1 合规：6/6 H 臂 cell 全部 `round1_compliant=true`。
- H 臂单 run token 成本 1.01M–1.90M（B 臂为 0）。
- 结论：开发性 pilot，n 太小，无统计显著信号（符合预期定位）。

## 注意事项

- **不要提交**：`run_bundle/`、`pilot_bundle/`、`cold_pilot_bundle/`、`run_matrix_results.json`、
  `*.log`、`.env`、API key、Julia/PySR 缓存、私有 benchmark 资产。
- **数据缺失报错**：先跑第 3 步 acquire + prepare，再 build。
- **H 臂失败排查**：看 `<cell>/run.log`。slim 治理下 controller directive 默认 advisory
  （`binding=false`，`deterministic_policy` 未启用），LLM 应遵循 `plan.md` 的
  `next_strategy`；`search.max_evals` 归 controller 所有，LLM 不得改。
- **复现性**：seed 由 `.hamilton_seed_plan.json` 注入（同一 repeat 内三轮同 seed），
  任务/seed 不在此目录的 config 中，而在每个 workspace 的 `task.md` + seed plan 里。
- **promotion token 预算（重要）**：`configs/hamilton/config_hcc_hybrid_pilot.yaml` 的
  `experiment.promotion.max_tokens: 400000` 对 dynamic_d01 任务偏低。本次
  `dynamic_d01/repeat_2` 第 3 轮 promotion 阶段因超过 40 万 token 被
  `Token budget preflight` 截断，round-3 晋升（真实分数 0.54047，已产生并验证于
  `history/round3/results/result.json`）未写回 `.hamilton_search_state.json`，incumbent
  停在 round-1 的 0.82218（主判据按平局计）。dynamic 类任务复现时建议把
  `promotion.max_tokens` 提到 ≥1000000。注意 manifest 的
  `max_hamilton_tokens_per_run: 3000000` 是每 run 软上限（collect 阶段标记），而
  `promotion.max_tokens` 是 promotion 阶段的**硬**上限（超限即截断）。
