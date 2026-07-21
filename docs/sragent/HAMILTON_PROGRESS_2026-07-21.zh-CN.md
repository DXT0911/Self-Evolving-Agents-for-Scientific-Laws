# Hamilton 两日研究与改进总结

> 时间范围：2026-07-19 至 2026-07-21
> 当前工作分支：`sragent/summer-2026`
> 上游基线：[`HyNlity/Self-Evolving-Agents-for-Scientific-Laws@040c0d1`](https://github.com/HyNlity/Self-Evolving-Agents-for-Scientific-Laws/commit/040c0d1f182222d3417c0ba27913a62282924a2b)
> 当前状态：改进均位于本地未提交工作区，尚未 commit、push 或合并到 GitHub。

> 编者注：以上“当前状态”是本报告形成时的历史快照。随后进行的工作区审计、事实口径修订
> 与分批固化见 `WORKTREE_AUDIT_2026-07-21.zh-CN.md` 和本分支 Git 历史；本报告中的实验
> 观察没有因此升级为正式科研结论。

## 1. 一句话结论

最开始的 Hamilton 已经提出了正确的总体框架：单 Agent、HCC 分层记忆，以及
Discovery → Verification → Promotion → Finish 四阶段循环；但它主要依靠提示词要求
Agent 自觉完成实验与科学判断，更接近一个设计原型。

经过这两天的共同研究，Hamilton 已经增加了标准化实验执行器、候选统一验证、搜索
标准化与原单位回变换、结构化残差诊断、严格单轮闭环证明、科学晋升审计、文献先验、
benchmark 答案隔离、分级 OOD、数据访问控制、token/evaluation 预算，以及 Julia/PySR
运行前检查。它已从“会被要求做研究的 LLM”向“受到机器可验证协议约束的 SR 研究
Agent”迈进。

但当前还不能声称 Hamilton 已经完成：我们尚未跑通一次满足全部科学治理条件的正式
多轮闭环，VIV 第一轮方程的拟合能力也仍然不足。

## 2. 比较口径

### 最开始的 Hamilton

以协作者仓库 `upstream/main` 的提交 `040c0d1` 为基线。开始研究时，本地分支和
`upstream/main` 都指向这个提交，因此不是凭印象比较，而是可以用 Git 精确复原。

基线代码与设计：

- [Hamilton README](https://github.com/HyNlity/Self-Evolving-Agents-for-Scientific-Laws/blob/040c0d1f182222d3417c0ba27913a62282924a2b/playground/hamilton/README.md)
- [多轮编排器](https://github.com/HyNlity/Self-Evolving-Agents-for-Scientific-Laws/blob/040c0d1f182222d3417c0ba27913a62282924a2b/playground/hamilton/core/playground.py)
- [单轮执行器](https://github.com/HyNlity/Self-Evolving-Agents-for-Scientific-Laws/blob/040c0d1f182222d3417c0ba27913a62282924a2b/playground/hamilton/core/exp.py)
- [四阶段系统提示词](https://github.com/HyNlity/Self-Evolving-Agents-for-Scientific-Laws/blob/040c0d1f182222d3417c0ba27913a62282924a2b/playground/hamilton/prompts/hamilton_system.txt)
- [原始 VIV task](https://github.com/HyNlity/Self-Evolving-Agents-for-Scientific-Laws/blob/040c0d1f182222d3417c0ba27913a62282924a2b/playground/hamilton/workspace/task.md)

### 现在的 Hamilton

指上述提交加上 2026-07-19 至 2026-07-21 的本地未提交改动及本地实验产物。由于这些
改动尚未进入 Git 历史，必须保留当前工作区或及时整理提交，否则无法仅靠 Git 恢复。

## 3. 对比总表

| 维度 | 最开始 | 现在 | 当前成熟度 |
|---|---|---|---|
| 定位 | 通用符号回归 Agent，VIV 为案例 | 明确坚持通用 SR Agent，VIV 仅作深度验证引例 | 设计定位清楚 |
| 四阶段循环 | Prompt 中规定四阶段 | 每轮必须留下结果、trace、findings、plan、finish 和结构化决策证明 | 已实现，尚未端到端通过 |
| 实验执行 | Agent 临时写 PySR 脚本 | JSON 配置驱动的统一 `run-sr-experiment` skill | 已实现并实跑 |
| 数据划分 | 主要靠任务文字约定 | 连续时间尾块验证，路径与训练文件 allowlist 强制检查 | 已实现 |
| 方程搜索尺度 | 直接在原尺度搜索 | 对 x、v、a 用训练块统计量标准化搜索，再自动还原原单位方程 | 已实现并实跑 |
| 候选选择 | 主要依赖 PySR loss/Agent 判断 | 同时考虑验证 NRMSE、短 ODE 轨迹误差、复杂度与失败惩罚 | 已实现 |
| 残差诊断 | Prompt 泛称“残差分析” | 分布、状态相关、分箱、相位、半径、自相关、DW、趋势和频谱 | 已实现 |
| OOD | Prompt 中建议做测试/OOD | Tier 0–3、冻结候选、SHA-256、私有访问账本、Tier 3 最终锁 | 代码与合约测试完成，未正式验收 |
| 科学晋升 | 更新 L2 即可 | incumbent 初始化/保留/晋升、promotion gates、证据强度、量纲尺度审计 | 已实现，真实 Promotion 尚未通过 |
| 多轮适应 | 下一轮由 Agent 自主改 | 必须针对失败门槛，每轮只改一个配置叶字段并给出可证伪预期 | 已实现 |
| 文献先验 | task.md 直接提供物理知识 | 文献检索生成带来源的宽泛定性先验，禁止给方程模板 | 已实现 |
| 答案泄露 | task.md 明文给参考方程和系数 | 公开 task 与 benchmark 私有答案分离，LLM 只能看到训练侧信息 | 已实现 |
| 数据安全 | LLM 可直接看到 workspace CSV | 文件工具禁止读取 CSV/TSV 等，并限制在当前 workspace | 已实现 |
| 预算治理 | 只有轮数和 turn 限制 | LLM 总 token、每轮 token、PySR 累积 evaluations、停滞停止 | 已实现，配置尚待统一 |
| 环境可靠性 | 正式轮内才 import PySR | 第一轮前检查 JuliaPkg 锁并预热 PySR/SymbolicRegression | 已实现并验收 |
| 测试 | TODO 仍要求完整多轮和 PySR 验证 | 40 个核心 contract tests + 4 个 preflight tests | 44 项通过 |

## 4. 这两天具体完成了什么

### 4.1 重新明确研究目标：Hamilton 不是 VIV 专用 Agent

我们首先厘清了 VIV 的角色：它不是 Hamilton 的硬编码任务，而是一个足够困难的非线性
动力学案例，用来暴露通用 SR Agent 在结构搜索、轨迹验证、跨工况泛化和科学判断上的
缺陷。

相应地，新增能力尽量位于通用层：配置驱动 runner、候选评分、残差接口、闭环审计、
OOD 协议和预算控制。VIV 特有的变量含义和动力学验证仍留在任务配置或可替换验证器中。

### 4.2 将 DeepSeek 接入方式改为环境变量

Hamilton 配置切换为 `deepseek-v4-pro` 和 DeepSeek OpenAI-compatible endpoint，API key
改用 `${HAMILTON_API_KEY}`，不再把凭证直接写在配置文件中。

需要注意：聊天中曾经出现过一个 API key，该 key 应视为已经暴露并在服务端撤销，后续
只在本机环境变量中配置新 key。

### 4.3 新增标准 SR 实验 Skill

新增 `evomaster/skills/run-sr-experiment/`，核心思想是：LLM 只负责提出假设和填写 JSON
实验配置，统一 runner 负责真正执行。这样避免每轮临时写脚本造成口径漂移、错误难以复现
和预算不可控。

统一 runner 现在负责：

- JSON schema 和路径边界验证；
- 训练数据 allowlist；
- 时间有序的连续尾块验证，避免时序随机切分泄露；
- 确定性串行 PySR、固定随机种子；
- PySR evaluations 累积预算账本；
- 多候选统一评估与重排；
- 短时 ODE 积分与失败惩罚；
- 原始单位方程、数据指纹、环境版本和结构化失败记录；
- 紧凑摘要返回 LLM，原始 CSV 不发送给模型。

### 4.4 修正不同量纲导致的搜索问题

我们发现直接在 x、v、a 原始尺度上搜索会使量级较大的变量和系数主导优化，影响 PySR
发现结构。于是加入：

1. 仅用 discovery block 拟合均值和标准差；
2. 在标准化变量中让 PySR 搜索；
3. 将每个候选解析为符号表达式；
4. 自动代回均值、尺度，恢复成 x、v、a 原始单位下的方程；
5. 所有验证和 ODE 积分都在原单位执行。

这既改善数值条件，又避免报告一个只有标准化坐标意义的方程。线性拟合只保留为数据管线
诊断，并明确禁止把它当作“发现的方程”。

### 4.5 建立候选科学评分和动态验证

最初的 PySR loss 只能回答逐点加速度拟合是否好，不能保证方程积分后仍然稳定、轨迹合理。
现在 runner 会对多个候选分别计算：

- 训练和连续验证块的逐点指标；
- 短时间 ODE 积分状态与轨迹误差；
- 方程复杂度；
- 数值积分失败惩罚。

当前科学评分用于候选重排，分数越低越好。它还不是最终的领域科学结论；长期吸引子、
多初值和跨工况结构仍需更强验证器。

### 4.6 增加结构化残差诊断

残差分析从 prompt 中的一句话变为机器可读输出，包括：

- 残差均值、RMSE、NRMSE、最大绝对误差；
- 残差与状态变量、绝对状态变量的相关性；
- 使用训练块确定边界的 feature bins；
- 振子标准化半径和相位分箱；
- 自相关、最强滞后、Durbin–Watson；
- 线性趋势；
- 主导频率、频率集中度和高频功率比例。

治理规则强调：一个残差模式并不能唯一确定缺少哪个方程项。下一轮策略必须同时写出替代
解释、风险和可证伪结果，不能从“残差与 v 有关”直接跳到预设某个 v 的幂次项。

### 4.7 把四阶段闭环变成机器可验证合约

基线只检查 `findings.md` 和 `plan.md` 的修改时间，即使没有结果文件、没有 finish 或科学
判断不完整，也可能继续下一轮。

现在单轮 closure 会验证：

- Agent 是否调用 `finish`；
- `trace.md` 是否更新；
- `findings.md` 与 `plan.md` 是否更新；
- 是否产生新的、状态为 completed 的结果 JSON；
- 第一轮文献先验是否有效；
- scientific decision 是否通过；
- 若继续研究，是否存在下一轮契约；
- 第二轮以后是否发生有意义且唯一的配置字段变化。

任一条件失败，当前轮标记为 `closed=false`，多轮控制器立即停止，不再把“程序返回了”误报
为“科学闭环完成了”。

### 4.8 加入科学治理和 incumbent 审计

`plan.md` 中增加机器可读的 `EVO_SCIENTIFIC_DECISION`。系统会审计：

- 第一轮是初始化 incumbent，后续是保留还是晋升；
- 新候选只有分数严格更优且 promotion gates 全部通过时才能晋升；
- claim 只能标记为 observation、hypothesis、supported 或 confirmed；
- confirmed 必须有多项证据并测试过替代解释；
- 不得用不同单位的原始系数大小直接比较变量重要性；
- 下一步必须绑定一个失败门槛，只改一个通用配置字段；
- 必须声明预期效果、风险和能够推翻假设的观测；
- solver completed 不能单独成为 scientific success。

### 4.9 解决 benchmark 答案泄露

原始 VIV `task.md` 明文给出了 EvLOWN 参考方程族、近似系数、目标振幅、推荐模板和搜索
提示。这与“未知方程发现”直接矛盾。

现在公开任务只包含：研究目标、训练文件、变量与单位、中性计算基线、证据层级和成功规则。
参考方程、系数、测试记录、OOD 标签和目标幅值属于 controller 私有 benchmark 资产。

同时：

- 从 Agent workspace 移除了 test/OOD CSV；
- LLM 文件工具限制在 active workspace；
- CSV、TSV、Parquet、Feather 等扩展名禁止被 LLM editor 读取；
- runner 可以读取被允许的训练文件，但只返回摘要；
- 目录列表也隐藏受保护表格文件。

### 4.10 用文献检索建立宽泛物理先验

新增 `literature-grounding` skill 和 `literature_search` 工具。第一轮可以搜索恢复力、能量
注入与耗散、稳定极限环、量纲一致性和跨工况共享结构等宽泛事实，但不能搜索 benchmark
论文、参考方程、系数或项列表。

`EVO_INITIAL_PRIORS` 必须包含至少两个文献查询、至少两个可追溯来源和至少三个定性先验，
并明确 `candidate_template_proposed=false`。这使先验有来源，同时降低把答案模板提前注入搜索
的风险。

### 4.11 建立四级 OOD 体系

新增 controller-side OOD evaluator：

- Tier 0：训练记录的连续尾块，允许每轮使用；
- Tier 1：同一工况、不同初始状态，限次提供开发摘要；
- Tier 2：排除工况，只允许包含工况变量的共享方程；
- Tier 3：外部工况的一次性最终验收。

候选在 OOD 前冻结并记录 SHA-256 与 `freeze_id`。访问私有数据前先写账本，失败尝试也消耗
次数。Tier 3 不向 Agent 释放可用于继续调参的信息，最终 attestation 写入后锁定 workspace，
禁止继续自适应搜索。

目前这套能力已通过合约测试，但尚未对正式私有 VIV OOD 资产完成 Tier 1–3 验收。

### 4.12 增加预算与停止机制

新增三层预算：

- Agent 单次运行 token 上限，并在下一次请求前预估是否会超限；
- Hamilton 总 token 与每轮 token 上限；
- PySR 累积 `max_total_evals` 账本。

控制器还可以在 incumbent 连续多轮没有改善时停止。我们由此发现了一个真实问题：Promotion
本身可能消耗大量 token，若每轮 token 配额太紧，实验虽完成但 Agent 来不及写完科学决策和
调用 finish。因此后续应将执行、验证和 Promotion 做成显式可恢复阶段，并为 Promotion 预留
独立预算。

### 4.13 增加 Julia/PySR 预热和锁检查

一次多轮测试曾在 `juliapkg` 的 file lock 上等待 1800 秒，控制台又没有心跳，因此看起来
像“运行很久没有结果”。我们完成了：

- 区分真实活跃锁与仅存在的 lock 文件；
- 第一轮 LLM 调用前，在限时子进程中 import PySR；
- 启动 Julia 并执行 trivial eval；
- 加载 `SymbolicRegression`；
- 超时或加载失败时，在消耗 DeepSeek token 和 PySR evaluations 前快速终止；
- 将 PySR/Julia 版本和预热耗时写入实验记录。

本机验收结果：PySR 1.5.9、Julia 1.11.9，完整预热约 10.5 秒，锁和残留进程均已清理。

## 5. 实验过程和我们得到的认识

这两天并不只是写代码，还进行了多次逐步升级的实验：低预算 smoke、单轮 closure、科学
闭环重试、自适应多轮、受控长跑、Promotion 恢复和多轮测试。

其中不同阶段的证据不能混为一谈：

- 最早的 200 evaluations 单轮 smoke 找到近似 `a=-10.29x`，train/validation R² 都约
  0.02。它证明了工具链和四阶段可以走通，但几乎没有科学拟合价值；
- 旧版自适应流程曾连续运行三轮，validation R² 约 0.47，仍只找到 x 的位置非线性项，
  没有恢复速度通道。它说明多轮调用机制能够运行，也说明“多跑几轮”本身不会自动解决
  搜索偏差；
- 这组三轮发生在严格反泄露、结构化科学治理和新 OOD 协议完成之前，记录中还使用过参考
  方程对比，因此不能作为 blind benchmark 证据；
- 后来的受控长跑最好 validation R² 约 0.528，仍然主要是位置项；后续候选分数变差时，
  新的 incumbent 规则应保留旧候选，而不是盲目接受最新方程。

最具代表性的有效结果位于：

`runs/hamilton_multiround_20260720_151500/workspaces/task_0/history/round1/results/viv-u248-round1-001-fast.json`

其结果为：

- PySR 执行状态：completed；
- 运行时间：约 23.4 秒；
- 选择方程：`a = -161.055989348566*x - 7.73309606585896`；
- train R² 约 0.5005；
- validation R² 约 0.5277；
- complexity = 5；
- scientific score 约 0.9343；
- 5 秒短 ODE 可以完成积分，但结构化残差仍很强。

这个结果说明两件不同的事：

1. 标准 runner、标准化搜索、原单位回变换、候选评分、ODE 和残差流水线确实能端到端工作；
2. 当前搜索只找到近似线性恢复力，约一半加速度方差未解释，尚未发现足够好的非线性耗散/
   能量注入结构，因此科学任务没有完成。

残差中存在明显的相位、速度幅值和时间相关结构，但这些只能说明模型不完整，不能单独证明
缺失项一定是某个具体的 v 幂次或 VIV 特定模板。

## 6. 当前没有完成的事项

### 6.1 尚未跑通正式多轮科学闭环

最近一次 run 虽然已经产生第一轮结果并更新部分 L2，但 scientific decision 没有完全通过
incumbent、promotion gates、claim strength、scale diagnostics、next strategy 和 success
gates 审计，最终 `closed=false`，所以控制器正确地没有进入第二轮。

### 6.2 Promotion 阶段仍然过度依赖长对话

我们增加了严格审计，但 LLM 生成合格决策块所需上下文和 token 较多。多次恢复运行在调用
`finish` 前触发 token preflight。这说明治理规则已经能发现问题，但阶段恢复和 prompt 压缩
还需要工程化。

### 6.3 搜索质量仍然不够

当前代表性方程的 R² 约为 0.5，只能恢复主要线性恢复力。下一步需要在不泄露参考答案的前提
下，让 residual diagnosis 驱动逐轮单变量干预，并增加更有辨识力的长期动力学验证。

### 6.4 分级 OOD 尚未完成真实验收

Tier 1–3 的安全协议、冻结、账本和合约测试已经实现，但还没有用正式私有 manifest 做完
实际评估。尤其不能把内部连续验证或旧 test 文件结果称作最终 OOD 成功。

### 6.5 配置与实验资产需要整理

- 之前批准的 80 万 token 上限尚未落到正式多轮配置；
- 旧 run 中有可复用的第一轮结果，但模板 workspace 的 resume 路径无效；
- 当前进程没有 `HAMILTON_API_KEY`；
- 多个临时配置和 run 需要区分“保留证据”与“可删除调试产物”；
- 部分运行日志有 Windows 编码显示问题；
- 所有改动仍未 commit/push。

## 7. 对当前成熟度的判断

可以把 Hamilton 的成熟度分成四层：

| 层级 | 判断 |
|---|---|
| 研究流程设计 | 已较完整：四阶段、HCC、证据门槛、适应策略清楚 |
| 实验执行基础设施 | 已形成可用原型：标准 runner、验证、残差、预算、preflight 均可运行 |
| 单轮科学闭环 | 接近但尚未通过严格治理；执行已成功，Promotion/Finish 仍失败 |
| 多轮自主发现能力 | 尚未证明；没有三轮连续闭环，也没有得到高质量最终方程 |

因此最准确的表述不是“Hamilton 已经做好”，而是：

> Hamilton 已从提示词驱动的流程原型，升级为具有机器可验证实验与科学治理边界的 SR Agent
> 研究原型；其基础设施明显增强，但多轮自主改进效果仍是下一阶段需要验证的核心科研问题。

## 8. 暂停实验期间建议做的整理

1. 将当前混合工作区拆成若干小提交：安全隔离、标准 runner、残差诊断、闭环治理、OOD、
   preflight、文档与实验记录；
2. 给每个提交运行相应测试，避免一次巨大提交难以 review；
3. 整理一个干净的正式多轮配置，不复用无效模板路径；
4. 将第一轮 Promotion 改成确定性的“结果摘要 → 决策草稿 → 审计修复 → finish”阶段；
5. 增加一个合成方程 benchmark，验证 Hamilton 在已知 ground truth、无答案泄露时是否能恢复
   结构；
6. 再回到 VIV，比较 direct PySR、fit-only Hamilton 和 dynamics-aware Hamilton；
7. 只有在内部方法冻结后，才按 Tier 1 → Tier 2 → Tier 3 使用私有数据。

## 9. 关键本地文件索引

- `playground/hamilton/core/playground.py`：多轮预算、停止、final OOD lock、PySR preflight；
- `playground/hamilton/core/exp.py`：单轮 closure 与科学治理审计；
- `evomaster/skills/run-sr-experiment/`：标准实验 Skill 与 runner；
- `evomaster/skills/literature-grounding/`：初始文献先验协议；
- `playground/hamilton/core/ood_evaluator.py`：controller-side Tier 1–3；
- `playground/hamilton/core/pysr_preflight.py`：Julia/PySR 环境预检；
- `playground/hamilton/core/test_standard_runner.py`：runner、closure、governance、安全和 OOD 测试；
- `playground/hamilton/core/test_pysr_preflight.py`：preflight 测试；
- `playground/hamilton/workspace/task.md`：无参考答案的公开 VIV 任务；
- `docs/sragent/`：研究协议及各阶段运行任务说明。

---

这份报告总结的是“我们实现和观察到了什么”，不是最终科研结论。VIV 方程结果目前只能作为
流水线验收和失败诊断证据，不能作为 Hamilton 已完成通用科学定律发现的证明。
