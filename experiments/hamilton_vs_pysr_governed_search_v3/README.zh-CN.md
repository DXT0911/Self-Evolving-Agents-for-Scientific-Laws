# Hamilton vs PySR v3

V3 保留 v2 的四个正式实验臂，不新增 `continuation_schedule_pysr`。不改配置的分段
warm-start 只作为实现等价性测试，用来确认它与连续 ordinary PySR 的差异。

核心变化是 Hamilton 三轮共享同一个 PySR 进程、种群、随机状态和输出目录；证据不足时允许
选择 `continue`，而不是为了满足协议强行修改参数。首版只允许热修改
`search.parsimony`；`search.maxsize` 在整个会话中固定，因为 PySR 已保存的名人堂结构不能安全
热扩容。常驻 worker 丢失时明确失败，禁止静默重启。

开发自检已经证明：ordinary 2,000 evaluations 与 warm-start 1,000+1,000 得到完全相同的
最终公式、科学分数、验证 MSE 和验证 R²；分段路径的引擎实测 evaluations 仅多约 1%。另一次
自检确认第二轮可以保留搜索状态并热调 `search.parsimony`。这些结果只证明实现可用，不证明
Hamilton 优于 PySR。机器可读证据见 `warm_start_smoke_evidence.json`。

`static_s01` 单任务、单次重复的四臂小规模试点已经完成。四臂各有 3,000 次成功请求预算，
Hamilton 状态连续性和引擎计数均有证据；但最终 Promotion 未完成协议收口，且运行期间留有失败
尝试，因此状态为“试点完成、带运行审计缺陷”，不能作为确认性结论。结果和解释见
`PILOT_RESULTS.zh-CN.md`，机器可读证据见 `pilot_evidence.json`。
