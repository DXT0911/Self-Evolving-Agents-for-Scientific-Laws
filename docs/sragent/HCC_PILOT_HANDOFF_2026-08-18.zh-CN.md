# HCC 混合线路 pilot —— 交接记录（2026-08-18）

> 接续 `HAMILTON_HANDOFF_2026-08-17.zh-CN.md`。本文档记录 pilot 的当前进度、已修问题、未解决问题，供新对话继续改进。

## 1. 研究目标（一句话）

**HCC 混合线路（自由 LLM + 可读 plan.md/findings.md 记忆 + 发现→验证→提炼闭环）在 benchmark 上能不能稳定找到方程、成本可不可接受？**

按 v6 的测量纪律（冻结 manifest + 配对 seed + engine evals + 预注册判据）做最小 pilot 来回答。

## 2. 实验设计（已与用户确认，不要改）

- **两臂**：
  - **H（HCC）**：自由 LLM + 可读记忆 + `governance_mode: slim`，3 轮 × 1500 evals。
  - **B（基线）**：裸持久 warm PySR，3 轮 × 1500 evals，round1 用同一冻结配置、round2/3 只 continue 不做自适应（v6 arm_a 同款），零 LLM。
- **矩阵**：2 task × 3 seed × 2 arm = **12 run**。
  - 任务：`static_s02`（盲静态 4 特征）+ `dynamic_d01`（动力学导数 2 特征）。
  - seed：`8401, 8402, 8403`。
  - 模型 `deepseek-v4-flash`；预算 4500 evals/run（H 与 B 相同）。
- **主判据**：配对符号检验（6 对），比较最终 incumbent 的 `scientific_score`（**越小越好**，H < B → H 胜）。双侧 binomial，`development_pilot_only_not_confirmatory`。

## 3. 关键语义约定（容易踩坑，务必记住）

- `scientific_score` 是**最小化**（越小越好）：loss + complexity 惩罚；候选过不了 candidate_ranking 时加 `failure_penalty: 100.0`。
- **seed 注入**：`.hamilton_seed_plan.json` → `apply_controller_seed` 无条件覆盖 `search.random_state`。warm-start 禁止跨轮改 seed → 三轮同 seed。
- **warm-start 兼容约束**（`run_experiment.py:135-139`）：非 restart 的 `compatible_change_fields` **只能含 `search.parsimony`**。`unary_operators`/`binary_operators`/`maxsize` 改动需要 `round_action: "restart"`（会丢弃 warm 种群，本 pilot 禁用）。
- **trust_region 审计**（`run_experiment.py:928-1019` `audit_single_field_adaptation`）：每轮**恰好改一个字段**（无 `allow_noop_continue` 时 `minimum_changes=1`），锚点距离 ≤ `max_anchor_distance=2`。
- **closure 审计**（`promotion_exp.py:1419-1501` `_build_closure`）：要求 finish_called + trace/findings/plan updated + completed_results + meaningful_config_change + single_config_change + `scientific_decision.valid`。
- **`scientific_decision.valid` 依赖 `plan_quality_valid`**（`promotion_exp.py:1217-1288`）：LLM 在 `plan.md` 里写的 `next_strategy` 必须满足严格结构化字段（详见 §6 问题 5）。

## 4. 已建好的脚手架（都在 `experiments/hamilton_hcc_hybrid_pilot/`）

- `pilot_manifest.yaml` —— 冻结 manifest。
- `build_pilot.py` —— 物化 12 workspace + `run_matrix.json` + `freeze_lock.json`。
- `execute_baseline.py` —— B 臂执行器（无 LLM）。
- `collect_pilot.py` —— 配对比较/sign-test/成本/合规汇总。
- `PRE_REGISTRATION.zh-CN.md` —— 预注册判据。
- `configs/hamilton/config_hcc_hybrid_pilot.yaml` —— H 臂配置（slim 治理 + v4-flash）。

## 5. 框架代码改动（只有 2 处小 bug 修复，已提交在 working tree 未 commit）

| 文件 | 改动 | 原因 |
|---|---|---|
| `playground/hamilton/core/playground.py` | +13/-1，新增 `_search_control_active` | `governance_mode: slim` 之前没触发 `initialize_control`，导致 seed 注入/预算记账/trust-region 全失效。必须修。 |
| `evomaster/skills/run-sr-experiment/scripts/run_experiment.py` | +1 行 `normalized["verification"]["short_ode"] = short_ode` | `short_ode` 默认值校验后没持久化，冻结配置漏了它就 `KeyError`。防御性修复。 |

## 6. 遇到的问题与状态（5 个，前 4 个已修，第 5 个未解决）

### 问题 1 [已修] short_ode KeyError（6 个 H cell 全灭）
`build_pilot.py` 的 `frozen_round1_block()` 只写了 `{"residual_diagnostics": {"enabled": true}}`，漏了 `verification.short_ode`，runner 无条件读它 → KeyError。
**修法**：冻结配置改为照抄 `runner_config()` 完整 verification 块（short_ode + candidate_ranking + residual_diagnostics 5 字段）；同时给 run_experiment.py 加 1 行持久化。

### 问题 2 [已修] failure_penalty=100（score ~100 vs B ~0.02）
LLM 把 `candidate_ranking.weights.trajectory_nrmse` 猜成 1.0（正确 0.0）→ 候选过不了 ranking → +100 penalty。
**修法**：冻结配置补 `candidate_ranking`（trajectory_nrmse=0.0）+ task.md 强指令「逐字段照抄」。**已验证**：round-1 与 B 完全一致（score `0.024193735387507173`，方程 `0.079577*x1*x2/(x3*x4**2)`）。

### 问题 3 [已修] warm-start 不兼容（dynamic_d01/repeat_1、repeat_2）
LLM 改 `unary_operators`/`maxsize`，被 warm-start 拒绝（只允许 parsimony）。根因是我 task.md 里写了「例如加一个 unary 算子」。
**修法**：task.md 第 2/3 轮改为「只允许调 `search.parsimony`」。

### 问题 4 [已修] promotion token 预算截断（finish_called=False）
round-2 promotion 撞上 `promotion.max_tokens=200000`。`agent.py:167` 的 preflight 会为下一次补全预留 `llm.max_tokens=128000`，所以有效预算只有 ~72k，LLM 在写 plan.md 最后一步 + 调 finish() 之前被截断。
**修法**：`config_hcc_hybrid_pilot.yaml` 的 `promotion.max_tokens` 200000 → 400000。**已验证**：smoke 重跑后 `finish_called=True`。

### 问题 5 [未解决] next_strategy 审计仍失败（`scientific_decision.valid=False`）
即使预算修好、`finish_called=True`，round-2 的 `plan_quality_valid` 仍为 False，报错：
```
next strategy lacks linked residual evidence, alternative explanation,
expected residual change, risk, or falsification
```
**精确根因**（已定位到 `promotion_exp.py:1217-1288` 的 next_strategy 校验）：

LLM 在第 2 轮写的 `next_strategy`（在 `plan.md` 的 `EVO_SCIENTIFIC_DECISION` 块里）字段：
- 6 个字符串字段（diagnosed_failure/evidence/expected_effect/alternative_explanation/expected_residual_change/falsification）✅ 都有
- `risks` ✅ 非空 list
- `residual_evidence` ✅ 有 result_file + finding="both" + observed
- **但 `action` 字段整个缺失**（代码里 `strategy.get("action", "modify")` → 默认成 "modify"）
- **`config_field: "none (adaptive hold; await controller OOD tier release)"`** —— 是自由文本，过不了正则 `(?:data|search|verification)(?:\.[A-Za-z0-9_]+)+`
- **`config_patch: {}`** —— 空 dict，对 "modify" 要求 len==1，失败

**LLM 实际想表达的**：round 2 已经把 1/(4π) 精确找到（score 0.02419→0.02097），科学上正确的下一步是「自适应暂停、等控制器释放 OOD/Tier 证据」，也就是 `action: "continue"`（不改配置）。

**更深层的设计张力**（这是真正的难点，不只是字段没写对）：
1. 机器字段层面：LLM 把「暂停」写成了自由文本 `config_field`，而不是 `action:"continue" + config_field:null + config_patch:{}`。
2. 框架层面：即使写成 `action:"continue"`（不改配置），下一轮（round 3）会撞 `trust_region` 审计——它要求**每轮恰好改一个字段**（无 allow_noop），所以「不改配置」在 round 3 也过不了。也就是说框架的「3 轮固定 + 每轮必须改一个字段」和 LLM「第 2 轮就找到答案、想停」是**结构性冲突**。

## 7. 当前 workspace 状态（重跑前需要知道）

- **B 臂（bare_pysr）**：6 个 cell 全部完成（无 LLM，结果有效，round-1 与 H 一致）。
- **H 臂（hcc_llm）**：6 个 cell 的 round 1 全部 clean closed，round 2/3 全部失败：

| cell | round-2 discovery | promotion_input.json | 状态 |
|---|---|---|---|
| static_s02/repeat_1/2/3 | ✅ 成功（parsimony，score 0.02097） | 有 | 可 resume（重试 promotion） |
| dynamic_d01/repeat_2 | ✅ 成功 | 有 | 可 resume |
| dynamic_d01/repeat_1 | ❌ warm-start 失败 | 无 | 需重做 round-2 discovery |
| dynamic_d01/repeat_3 | ✅ 成功 | 有（跑完 exit 1） | 可 resume |

- 已无残留 python/julia 进程（已清理）。

## 8. H 臂重跑命令（每个 cell，来自 `run_matrix.json`）

```bash
cd D:/Physwarm学习/BSR/Self-Evolving-Agents-Hamilton-v2
python run.py --agent hamilton \
  --config configs/hamilton/config_hcc_hybrid_pilot.yaml \
  --task "Execute frozen HCC hybrid task <task_id>, <repeat_id>." \
  --run-dir experiments/hamilton_hcc_hybrid_pilot/pilot_bundle/hcc_llm/<task_id>/<repeat_id>
```

playground 会自动 resume（已 closed 的 round 1 直接跳过，round 2 重试 promotion / 重做 discovery）。运行需 `HAMILTON_API_KEY`（环境变量已配好）+ PySR/Julia 授权。多 cell 并行建议 stagger 3s 防止 WinError 10054。

## 9. 下一步建议（3 个方向，新对话可自选）

1. **改指令（最省事）**：在 task.md / system prompt 明确告诉 LLM——每轮必须 `action:"modify"` + 合法 `config_field:"search.parsimony"` + `config_patch:{"search.parsimony":<新值>}`，且 6 个字段 + risks + residual_evidence 一个不能少，禁止写「adaptive hold/暂停」这种自由文本。这能强制 3 轮都做 parsimony 微调、过审计。
2. **放宽治理**：H 臂改 `governance_mode: off`（跳过 scientific_decision 审计），只保留 closure 硬校验。但这改变了实验含义（slim 治理本来是重点）。
3. **当作实证结论**：H 臂第 2 轮就精确找到 1/(4π)、LLM 正确判断「该停」，但 slim 治理 + 固定 3 轮结构拒绝了这个正确决策 → 这本身就是「自由 LLM 的科学判断 vs 刚性治理」不匹配的结论，可以写进结果报告。

## 10. 关键文件位置

- 交接起点：`docs/sragent/HAMILTON_HANDOFF_2026-08-17.zh-CN.md`
- 本 pilot：`experiments/hamilton_hcc_hybrid_pilot/`（build/execute/collect + manifest + PRE_REGISTRATION）
- H 配置：`configs/hamilton/config_hcc_hybrid_pilot.yaml`
- next_strategy 审计：`playground/hamilton/core/promotion_exp.py:1217-1288`
- closure 审计：`playground/hamilton/core/promotion_exp.py:1419-1501`
- warm-start 约束：`evomaster/skills/run-sr-experiment/scripts/run_experiment.py:135-139`
- token preflight：`evomaster/agent/agent.py:167-177`
- 治理参考（next_strategy 完整结构）：`evomaster/skills/run-sr-experiment/references/scientific_governance.md`
