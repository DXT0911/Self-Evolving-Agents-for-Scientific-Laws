# Hamilton V6：LLM 主导的受控符号回归

V6 保留冻结的 V5 实验不变，并改变下一轮动作的决定顺序：

1. PySR 完成本轮搜索并生成数值诊断。
2. 控制器生成有限的合法候选动作，不再直接决定动作。
3. DeepSeek 选择候选动作；通过校验后，该选择成为下一轮 binding action。
4. API、JSON、token 或白名单校验失败时，使用确定性 fallback。
5. 每轮结束后更新证据记忆、`plan.md` 和包含真实结果的 `findings.md`。

## 默认运行边界

- 最少 3 轮，最多 8 轮。
- 每轮 1,500 requested evaluations，总上限 12,000。
- 连续 3 轮没有 incumbent 改善时停止。
- 第 3 轮以后，LLM 可以选择安全的 `stop` 候选。
- LLM 可以选择继续搜索、增大 parsimony、减小 parsimony或停止。
- LLM 不能自行填写任意配置、突破预算或使用白名单以外的变量和算子。

这些值都可以在 `configs/hamilton/config_llm_led_pysr_v6.yaml` 修改。

## PowerShell 运行

先从一个已经包含 `input/data.csv` 和 `round1_baseline.json` 的旧 workspace 创建干净的 V6 workspace：

```powershell
cd "path\to\Self-Evolving-Agents-for-Scientific-Laws"

python experiments\hamilton_vs_pysr_llm_led_search_v6\prepare_workspace.py `
  --source-workspace "旧的workspace路径" `
  --output-workspace "runs\hamilton_v6_first_run\workspaces\task_0"
```

在当前 PowerShell 会话设置 API Key，然后运行：

```powershell
$env:HAMILTON_API_KEY = "你的DeepSeek API Key"

python experiments\hamilton_vs_pysr_llm_led_search_v6\execute_llm_led_hamilton.py `
  --workspace "runs\hamilton_v6_first_run\workspaces\task_0"
```

## 主要输出

- `findings.md`：每轮真实方程、分数、实际动作和 LLM 判断。
- `plan.md`：下一轮 binding action。
- `history/roundN/llm_decision.json`：单轮 LLM 决策审计。
- `.hamilton_llm_decision_ledger.json`：调用状态、token 和 fallback 记录。
- `v6_llm_led_summary.json`：最终最佳方程、停止原因和完整轮次摘要。
