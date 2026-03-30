# Hamilton L3/Critic 工件契约

## Task 级工件
- `task.md`：任务契约。
- `plan.md`：L2 战略与当前最优。
- `findings.md`：L2 研究发现。
- `l3_context.md` / `l3_context.json`：Hamilton 在 task 启动时读取的共享记忆上下文。
- `variable_memory.json`：变量角色记忆。
- `routing_state.json`：路线选择与历史。
- `hypothesis_archive.jsonl`：候选假设档案。
- `falsification_log.jsonl`：证伪记录。
- `l3_promotion_summary.json`：task 结束时的共享记忆 promotion 摘要。

## Round 级工件
- `history/round{N}/trace.md`：L1 工作记忆。
- `history/round{N}/proposal.md` / `.json`：Hamilton 提案。
- `history/round{N}/critic_report.md` / `.json`：Critic 攻击报告。
- `history/round{N}/critic_l3_context.md` / `.json`：Critic 专属共享记忆上下文。
- `history/round{N}/repair_or_rebuttal.md` / `.json`：Hamilton 对 critic 的修复或反驳。
- `history/round{N}/gate_result.json`：系统 gate 判定。

## Critic JSON 契约
- `summary`
- `overall_recommendation`
- `critiques[]`
- `critiques[].id`
- `critiques[].claim_under_attack`
- `critiques[].risk_type`
- `critiques[].severity`
- `critiques[].required_check`
- `critiques[].acceptance_bar`
- `critiques[].evidence`

## Repair JSON 契约
- `summary`
- `responses[]`
- `responses[].critique_id`
- `responses[].status` (`accepted_and_fixed` / `rejected_with_evidence` / `deferred_next_round`)
- `responses[].evidence`
- `next_round_focus[]`
