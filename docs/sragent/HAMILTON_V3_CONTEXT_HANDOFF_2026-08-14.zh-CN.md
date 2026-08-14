# Hamilton v3 研究交接（新 Codex 上下文）

更新日期：2026-08-14
研究状态：v3 四臂开发试点已完成；性能未达标；下一阶段应先改进方法和运行可靠性，不应直接扩大实验。

## 1. 一句话结论

Hamilton 已经能够在三轮之间真正保留同一个 PySR 搜索状态，也在一次试点中胜过了三次独立
重启；但它仍明显不如一次连续运行的 ordinary PySR，LLM token 成本又很高。因此当前成果是
“搜索延续机制实现成功、Hamilton 性能策略尚未成功”，不能声称 Hamilton 优于 PySR。

VIV 长期动力学研究已经暂停，不属于当前研究范围。

## 2. 权威仓库状态

- GitHub：`https://github.com/DXT0911/Self-Evolving-Agents-for-Scientific-Laws`
- 当前开发分支：`experiment/hamilton-pysr-v3`
- 本机独立 worktree：`D:\Physwarm学习\BSR\Self-Evolving-Agents-Hamilton-v2`
- v3 基础提交：`f43f4f3 add persistent warm-start search for Hamilton v3`
- 当前结果提交：`11b6ea2 complete Hamilton v3 four-arm pilot`
- 草稿 PR：`https://github.com/DXT0911/Self-Evolving-Agents-for-Scientific-Laws/pull/3`
- PR base：`experiment/hamilton-pysr-v2`
- 截至本文创建前，工作树干净，当前分支与 `origin/experiment/hamilton-pysr-v3` 一致。

不要在旧的 `sragent/summer-2026` 主工作树里继续 v3 开发，也不要重复运行已完成的 v2 gate 或
v3 pilot。原始运行 bundle 被 Git 忽略并保留在本机；Git 中保存的是紧凑证据、配置、协议和哈希。

## 3. 研究问题和四个评价目标

研究问题不是“让 LLM 直接猜方程”，而是：Hamilton 能否依据确定性验证、残差诊断和历史
L2 记忆，更有效地控制 PySR 的后续搜索，并在公平预算下优于普通 PySR。

后续实验仍需同时评价四个目标：

1. **终点精度**：公开验证集 NRMSE，报告 Hamilton 减去各基线的配对差值。
2. **恢复与可靠性**：真实方程严格等价、变量 precision/recall、复杂度、结构化闭环和失败惩罚。
3. **搜索效率**：引擎实测 evaluations、best-so-far 曲线面积、达到 NRMSE 阈值所需 evaluations。
4. **控制成本**：LLM input/output/reasoning token、墙钟时间、Promotion 尝试和 PySR 额外开销。

Token 与 evaluations 必须分开报告，不能互相折算。

## 4. 固定的四个实验臂

1. `ordinary_pysr`：一次连续 PySR 搜索。
2. `fixed_schedule_pysr`：三段相同 seed、相同基础配置的独立重启。
3. `union_schedule_pysr`：同样独立重启，但从开始就拥有完整候选算子并集。
4. `governed_hamilton`：三轮受治理搜索，轮间保留同一个 PySR worker、种群和随机状态。

不要新增 `continuation_schedule_pysr` 正式实验臂。不改变配置的分段 warm-start 已通过等价性
smoke，它只是 ordinary continuous PySR 的实现校验，不是独立科学对照。

## 5. v3 已实现的关键能力

- Hamilton 三轮共享一个常驻 `PySRRegressor(warm_start=True)` 进程和搜索状态。
- 允许治理动作 `continue`，不再强迫每轮修改参数。
- 当前只允许热修改 `search.parsimony`；`search.maxsize` 在会话内固定，因为已有 PySR
  hall-of-fame 状态不能安全热扩容。
- worker 丢失时明确失败，禁止静默重启后冒充连续搜索。
- 每轮保留 requested-evaluation 账本，同时记录增量 `SearchState.num_evals` 作为引擎实测值。
- Windows IPC 改为 `.hws/<12位哈希>/q|r/<16位ID>.json`，避免旧路径长度限制。
- 原子 JSON 写入使用唯一临时文件，并短暂重试 Windows `PermissionError`。
- 被外部中断遗留的账本 reservation 可以审计地结算为 failed，不删除历史。

开发 smoke 已证明：ordinary 2,000 evaluations 与 warm-start 1,000+1,000 的最终公式和指标
完全相同，分段引擎开销约 1%；第二轮热调 parsimony 时搜索状态仍得到保留。

## 6. 最近一次四臂试点

任务：`static_s01`，`repeat_1`，seed `7101`。每臂有 3,000 次**成功请求** evaluations。
这是单任务、单次重复的开发试点，不是确认性实验。

| 排名 | 实验臂 | 科学分数（低为好） | 验证 NRMSE | 验证 R² | 引擎实测 evaluations |
|---:|---|---:|---:|---:|---:|
| 1 | ordinary PySR | 0.1119 | 0.0812 | 0.9934 | 3,876 |
| 2 | union schedule | 0.1557 | 0.1267 | 0.9840 | 4,539 |
| 3 | Hamilton v3 | 0.2683 | 0.2183 | 0.9523 | 4,306 |
| 4 | fixed schedule | 0.3384 | 0.2965 | 0.9121 | 3,903 |

Hamilton 三轮实测 evaluations 为 1,301 / 1,578 / 1,427，状态连续性为 true。搜索阶段约
43.6 秒，治理使用 541,751 LLM token。四臂都没有严格恢复真实公式。

因此只能得出：

- warm-start 机制有效，且本次优于 matched restart；
- Hamilton 没有胜过 ordinary PySR 或 union schedule；
- 当前瓶颈主要是治理决策质量和成本，而不是继续增加 token；
- 一次结果不能判断跨数据集或跨 seed 的稳定性。

## 7. 必须保留的运行与审计事实

试点状态是 `completed_with_operational_audit_failures`，不是干净的正式完成：

- Hamilton 前两次 round 1 因 Windows 长路径在 PySR 启动前失败，实际引擎 evaluations 为 0；
  两个 1,000 evaluation 的保守 reservation 仍作为 failed 审计记录保留。
- 最终 Promotion 的 scientific decision 有效，但在 fit-token 预检前没有调用 `finish`，所以
  `hamilton_final_promotion_closed=false`。不要把它描述为完整闭环。
- 三个控制臂曾并行启动并触发 Julia LLVM 内存不足；之后改为串行，四臂有效结果均已完成。
- 外部中断造成的 orphan reservations 已原位结算为 failed；当前
  `no_orphaned_reserved_attempts=true`。
- failed reservation 是保守账本额度，不必然等于引擎实际消耗。科学比较仅采用 completed
  结果中各臂成功的 3,000 requested evaluations。

不要清理、覆盖或把 failed 记录改写为 completed，也不要把 reservation 总数加进有效实验预算。

## 8. 新上下文首先要阅读的文件

按顺序完整阅读：

1. `docs/sragent/HAMILTON_V3_CONTEXT_HANDOFF_2026-08-14.zh-CN.md`（本文）
2. `experiments/hamilton_vs_pysr_governed_search_v3/README.zh-CN.md`
3. `experiments/hamilton_vs_pysr_governed_search_v3/PROTOCOL.md`
4. `experiments/hamilton_vs_pysr_governed_search_v3/manifest.yaml`
5. `experiments/hamilton_vs_pysr_governed_search_v3/PILOT_RESULTS.zh-CN.md`
6. `experiments/hamilton_vs_pysr_governed_search_v3/pilot_evidence.json`
7. `experiments/hamilton_vs_pysr_governed_search_v3/pilot_manifest.yaml`
8. `experiments/hamilton_vs_pysr_governed_search_v3/warm_start_smoke_evidence.json`
9. `experiments/hamilton_vs_pysr_governed_search_v2/RESULTS.zh-CN.md`
10. `experiments/hamilton_vs_pysr_governed_search_v2/dataset_split.yaml`
11. `playground/hamilton/DEVELOPMENT.zh-CN.md`
12. `docs/sragent/RESEARCH_PROTOCOL.zh-CN.md`

实现入口：

- `evomaster/skills/run-sr-experiment/scripts/run_experiment.py`
- `evomaster/skills/run-sr-experiment/scripts/warm_start_worker.py`
- `playground/hamilton/core/promotion_exp.py`
- `playground/hamilton/core/standard_runner.py`
- `experiments/hamilton_vs_pysr_governed_search_v3/build_pilot.py`
- `experiments/hamilton_vs_pysr_governed_search_v3/collect_pilot.py`

## 9. 下一阶段建议（按优先级）

### P0：修复 Promotion 过早退出

目标是让“有效 scientific decision 已存在”的情况下能够确定性完成 L2 更新和 `finish`，而不是
再启动一次很长的自由对话。优先检查 `promotion_exp.py` 的 preflight、恢复和闭环顺序；添加针对
“token 预检发生在 finish 前”的回归测试。修复只能改善运行可靠性，不能回写或伪造本次试点。

### P0：降低治理 token 成本

目前 541,751 token 换来的结果仍差于 ordinary PySR。建议把 LLM 的输出限制为小型结构化动作：

- `continue`
- 在预先声明的范围内调整 `parsimony`
- 对下一轮提出一条可证伪假设
- 在达到冻结条件时停止

由确定性 controller 完成结果摘要、合法性校验、L2 materialization 和 finish。先用既有结果做
离线 replay，比较不同决策规则，不要一开始重新调用 PySR。

### P1：改进动作策略，而不是增加自由参数

当前证据说明无条件调参可能破坏搜索。应把 `continue` 作为强基线或默认动作，只有达到预先
声明的残差/停滞阈值才允许改变 parsimony。不要立即开放 maxsize 热修改；若确需改变 maxsize，
应作为显式重启动作并与控制臂公平计账。

可以先检验以下假设：

1. incumbent 仍在改善时，继续搜索优于调参；
2. 只有 best-so-far 长期停滞且复杂度明显过高/过低时才调整 parsimony；
3. 动态数据残差高度自相关时，不根据单轮残差直接提高表达式复杂度；
4. LLM 只负责提出候选假设，确定性 policy 根据冻结阈值选择动作，是否比 LLM 直接控制更稳定。

### P2：完成小规模多 seed 开发验证

仅在 P0 修复、离线 replay 和单元测试通过后，冻结新 pilot manifest。优先使用开发任务，不打开
sealed test，也不恢复 VIV。建议先以至少 3 个 paired seeds 检验普通连续 PySR、fixed restart、
union 和新 Hamilton policy；额度必须在运行前冻结并由用户确认。若小规模结果仍不能稳定改善
ordinary PySR，应回到策略设计，不要直接扩大 token 或 evaluations。

## 10. 安全、公平性和禁止事项

- 开始时只做只读检查，不直接运行 PySR、Julia、DeepSeek 或新实验。
- 不打开 sealed test，不重新使用 VIV，不重复 v2 gate 或本次 v3 pilot。
- 四臂必须共享相同公开数据字节、划分、基础配置、配对 seed 和成功 requested-evaluation 预算。
- Hamilton 先产生预算轨迹；给控制臂的冻结包只能含预算和 seed，不能含 Hamilton 方程、score、
  残差、自然语言决策或 L2。
- 参考方程只能由 controller 使用，不能复制进 Agent workspace。
- 不提交 API key、`.env`、provider 日志、原始 run bundle、缓存或 private/OOD 资产。
- 不使用 `git reset --hard`、`git clean`、强推或删除审计失败记录。
- 新实验、额外 evaluations 或 token 额度必须先给出冻结方案并获得用户明确授权。
- Windows 上控制臂应串行运行，除非经过内存上限验证。

凭据变量名是 `HAMILTON_API_KEY`，只从环境读取。不要在日志或交接文档中打印真实 key。

GitHub CLI 在 Codex 沙箱内可能错误显示 keyring token 无效；同一命令在获准访问 Windows 用户
环境后可以正常读到现有登录。遇到这种情况先区分沙箱凭据可见性与真实失效，不要立即要求用户
重新登录或输出 token。

## 11. 离线验证命令

以下命令不应调用 DeepSeek 或运行新的 PySR 搜索：

```powershell
python -m unittest `
  playground.hamilton.core.test_repository_navigation `
  playground.hamilton.core.test_config_catalog `
  playground.hamilton.core.test_warm_start_runner `
  playground.hamilton.core.test_standard_runner `
  playground.hamilton.core.test_pysr_preflight
```

当前基线是 105 tests passed。若数量或结果变化，先解释原因。

## 12. 可直接复制给新 Codex 的提示词

> 请继续 Hamilton v3 的性能研究。仓库 worktree 是
> `D:\Physwarm学习\BSR\Self-Evolving-Agents-Hamilton-v2`，权威分支是
> `experiment/hamilton-pysr-v3`。开始时先运行只读的 `git status -sb`、当前分支、remote、最近
> 10 个提交和 worktree 检查，不要直接运行任何 PySR、Julia、DeepSeek 或新实验。完整阅读
> `docs/sragent/HAMILTON_V3_CONTEXT_HANDOFF_2026-08-14.zh-CN.md` 中第 8 节列出的文档和证据。
> v3 四臂 `static_s01` pilot 已完成，禁止重复运行；它证明 persistent warm-start 有效并胜过
> fixed restart，但 Hamilton 明显不如 ordinary PySR 和 union，且消耗 541,751 LLM token。
> 当前 pilot 带审计缺陷：最终 Promotion scientific decision 有效，但未调用 finish；failed
> reservations 必须保留，当前没有 orphan reservation。VIV 已暂停，sealed test 不得打开，
> `continuation_schedule_pysr` 不是正式实验臂。你的第一项工作是只读诊断 Promotion 为什么会在
> fit-token preflight 前退出，并提出最小修复、回归测试与降低治理 token 成本的离线 replay
> 方案。先向我报告根因、拟修改文件、风险、测试和冻结后的下一次小规模实验设计；在我明确授权
> 前不要实施新实验或增加任何 token/evaluation 额度。保护用户改动，不提交 key，不删除或改写
> 审计记录，不使用 reset hard、git clean 或强推。

## 13. 完成标准

下一阶段不是“多跑几次”就算完成。至少应满足：

1. Promotion 过早退出有可复现回归测试并被最小修复；
2. 相同冻结结果的离线 replay 能比较决策规则且不调用 PySR；
3. Hamilton 单任务治理 token 明显下降；
4. 新策略和停止/调参阈值在实验前冻结；
5. 多 seed 开发结果至少显示 Hamilton 相对 ordinary PySR 的稳定改善趋势，才考虑验证集。

若第 5 项不成立，应诚实得出当前 Hamilton 控制策略没有带来性能优势，而不是继续追加额度。
