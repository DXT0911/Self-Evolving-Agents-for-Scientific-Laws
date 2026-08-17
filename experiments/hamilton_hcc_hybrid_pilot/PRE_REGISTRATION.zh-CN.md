# HCC 混合线路 pilot —— 预注册判据

日期：2026-08-18
状态：**frozen_pre_execution**（本文件在运行前定稿，运行后不得改动）

## 1. 研究问题

HCC 混合线路（自由 LLM + 可读 plan.md/findings.md 记忆 + 发现→验证→提炼闭环）在 benchmark 上，
相对**同 seed / 同预算 / 同起点的裸持久 PySR**，能否找到更好的方程、成本可不可接受？

## 2. 两臂

- **H（hcc_llm）**：自由 LLM，slim 治理，3 轮 × 1500 evals。
- **B（bare_pysr）**：裸持久 warm PySR，3 轮 × 1500 evals，round1 用同一冻结配置、round2/3 只 continue 不做自适应，零 LLM 调用。

两臂唯一差异：H 有 LLM 在 round2/3 自适应搜索配置，B 没有。

## 3. 冻结矩阵

- 任务：`static_s02`（盲静态 4 特征）、`dynamic_d01`（动力学导数 2 特征）。
- seed：`8401, 8402, 8403`（复用 v6 冻结 seed 集前 3 个）。
- 每 run 预算 4500 evals；模型 `deepseek-v4-flash`。

## 4. 冻结 round-1 搜索配置（H 与 B 同一起点）

- `search.binary_operators: [+, -, *, /]`，`search.unary_operators: []`
- `search.niterations: 40`，`search.maxsize: 31`，`search.parsimony: 0.001`，`search.max_evals: 1500`
- `search.populations: 8`，`population_size: 32`，`tournament_selection_n: 12`，`top_k: 10`
- `verification.residual_diagnostics.enabled: true`（跨轮固定）

seed 由 controller 强制注入（`.hamilton_seed_plan.json`），LLM 无权设 `search.random_state`。

## 5. 主判据（预注册）

- **指标**：每 run 的**最终 incumbent scientific_score**（`selected.scientific_score`）。
- **方向**：**minimize（越小越好）**——runner 层 "Minimize scientific score"。
- **比较**：配对符号检验（sign test）。对每个 (task, seed) 配对，H < B → H 胜；
  H > B → H 负；差 < 1e-12 → 平局。
- **检验**：6 对样本，双侧 binomial 检验，记录 (H 胜, H 负, 平) 计数与单侧/双侧 p 值。
- **定性**：`development_pilot_only_not_confirmatory`（沿用 v6）——这是方向性证据，不是确认性结论。

## 6. 次判据（预注册）

1. **val R²**：每 run 最终 incumbent 的验证集 R²（越高越好，仅作描述性对照）。
2. **token 成本**：每 H run 的总 token（含 discovery + promotion），报告中位数/合计。
3. **engine evals 对齐**：H 与 B 各自 engine-measured 评估总数是否都约等于 4500（不得靠多花算力取胜）。
4. **closure 可靠性**：每 H run 的 closed 轮数（应 = 3）；缺失/失败轮显式记录。
5. **round-1 合规**：H 臂实际 round-1 `experiment.json` 的 search 算子/maxsize/parsimony/niterations
   是否与 §4 冻结值一致（不一致的 cell 标记为不合规，主判据中单独说明）。

## 7. 报告义务

- 所有 12 run 的原始证据（score、val R²、token、evals、closure、合规）写入 `pilot_evidence.json`。
- 不基于主判据作"LLM 有效"的确认性声明；仅报告方向 + 显著性 + 与 v6 负结论的对照。
