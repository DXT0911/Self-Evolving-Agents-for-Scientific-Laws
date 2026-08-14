# Hamilton vs PySR v3

V3 保留 v2 的四个正式实验臂，不新增 `continuation_schedule_pysr`。不改配置的分段
warm-start 只作为一次实现等价性测试，用来确认它与连续 ordinary PySR 的差异。

核心变化：Hamilton 三轮共享同一个 PySR 进程、种群、随机状态和输出目录；证据不足时
允许选择 `continue`，而不是为了满足协议强行修改参数。首版只允许修改
`search.parsimony`。`search.maxsize` 在整个会话中固定，因为 PySR 的已保存名人堂结构不能安全热扩容。
常驻 worker 丢失时明确失败，禁止静默重启。

开发自检已通过：ordinary 2000 evaluations 与 warm-start 1000+1000 得到完全相同的
最终公式、科学分数、验证 MSE 和验证 R²；分段路径的引擎实测 evaluations 仅多约 1%。
另一次自检确认第二轮可以保留搜索状态并热调 `search.parsimony`。这些结果只证明实现
可用，不是 Hamilton 优于 PySR 的科学结论；正式四臂实验尚未开始。

机器可读证据见 `warm_start_smoke_evidence.json`。
