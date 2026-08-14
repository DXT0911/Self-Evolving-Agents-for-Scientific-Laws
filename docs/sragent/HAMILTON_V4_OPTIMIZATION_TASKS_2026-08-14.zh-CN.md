# Hamilton v4 优化任务清单

更新日期：2026-08-14
状态：离线方法与控制基础设施已实现；未启动新 PySR/LLM 实验；未打开 sealed test。

## 目标

把 Hamilton 从“LLM 自由解释并直接调参”改为“LLM 提出受限结构假设，确定性 controller
负责动作、合法化、候选保留、回滚和预算”。所有策略先在冻结结果上离线回放，再决定是否进入
新的小规模开发实验。

## P0：权限划分与确定性 policy

- [x] 定义 LLM planner 白名单：假设、候选变量、候选算子、请求动作和证伪条件。
- [x] 禁止 planner 提交任意配置 patch、候选保留结论、score 或预算。
- [x] 定义 controller 动作：`continue`、warm-safe `modify`、`branch`、`rollback`、`stop`。
- [x] 默认规则：incumbent 仍改善或尚无持续停滞证据时选择 `continue`。
- [x] 只有持续停滞且复杂度/残差越过冻结阈值时才修改 `parsimony`。
- [x] 没有 warm-safe 干预但残差结构显著时，只提出需要 restart 的 `branch`，不伪装为 warm-start。
- [ ] 在新开发协议冻结后把 controller 推荐从审计建议升级为 binding；v3 历史协议保持兼容。

实现：`playground/hamilton/core/governed_policy.py`。

## P0：结构化信用分配

- [x] 将冻结方程展开为 additive terms。
- [x] 删除每个项后重新拟合其余线性权重，计算 held-out NRMSE 增量。
- [x] 对项数设置硬上限，失败时产生结构化状态而不是中断实验。
- [x] runner 支持可选 `verification.structural_diagnostics`，默认关闭以保护历史配置。
- [x] 对 v3 三轮结果完成离线项级诊断。
- [ ] 后续可评估 pairwise influence；在共线项上必须保留“条件性证据”边界。

实现：`playground/hamilton/core/structural_diagnostics.py`。
证据：`experiments/hamilton_vs_pysr_governed_search_v3/offline_structural_diagnostics_v4.json`。

## P1：anchor、分支、回滚和 L2 路由

- [x] 复用已有 incumbent anchor、trust region 和连续停滞回滚，不重复实现。
- [x] 增加四类 controller 记忆：`elite`、`motifs`、`failures`、`diagnostics`。
- [x] 按 improving、complex-valid、stagnant-structured、stagnant-unstructured、rollback
  状态只暴露必要记忆分区。
- [x] 将确定性 policy snapshot、动作建议和 routed memory view 加入下一轮 directive。
- [ ] 新协议若启用 `branch`，必须作为显式 restart 路径并单独计账；不得热改 maxsize/算子集合。

实现：`playground/hamilton/core/search_control.py`。

## P1：离线决策 replay

- [x] replay 只读取 completed result JSON，不调用 PySR、Julia、LLM 或 private evaluator。
- [x] 输出逐轮诊断、process state、建议动作和 action counts。
- [x] 明确声明 replay 不能估计未执行动作的反事实性能。
- [x] 在 v3 `static_s01` 三轮上运行：三轮均建议 `continue`。
- [ ] 在更多已存在的公开开发结果上回放并冻结阈值；不得用 sealed test 调阈值。

实现：`playground/hamilton/core/offline_policy_replay.py`。
证据：`experiments/hamilton_vs_pysr_governed_search_v3/offline_policy_replay_v4.json`。

## P1：成本和 Promotion

- [x] 新 policy 本身为纯确定性代码，不消耗 LLM token。
- [x] routed memory 限制暴露条目数，避免把全部历史重复放入 prompt。
- [x] 已有 artifacts 通过 deterministic audit 时，由 controller 写入恢复标记并直接完成
  `finish` 收口；不再发起第二次 LLM 调用，也不会伪造 LLM trajectory。
- [ ] 新开发配置为 planner 设置单次小型结构化输出预算；额度必须在运行前另行冻结。
- [ ] 记录 planner、Promotion 和总 token，禁止只报告总量。

## 验证门

- [x] 新增 10 个针对性离线测试，其中包括 token preflight 前 deterministic finish 回归。
- [x] 原 105 个离线测试与新增测试合计 115 个全部通过。
- [x] `git diff --check` 通过。
- [ ] 在用户确认新 manifest、paired seeds 和预算前，不运行新 PySR/LLM 实验。
- [ ] 小规模开发结果必须相对 ordinary PySR 呈现跨 seed 的稳定改善，才能考虑 validation。

## 当前离线结论

v3 三轮 scientific score 依次约为 `0.3384 → 0.2790 → 0.2683`。冻结 policy 在三轮均选择
`continue`：第一轮尚无持续停滞证据，第二、三轮 incumbent 仍在改善。项级诊断显示第三轮的
加性重拟合验证 NRMSE 明显低于前两轮，并将 `x1`、`x1*sin(x2)` 和 `x2` 识别为主要正贡献
结构。该结果支持“不要为了表现自适应而过早调 parsimony”，但不证明连续运行最终会胜过
ordinary PySR，也不构成未执行动作的反事实结果。
