# Hamilton 与 PySR 治理搜索 v2

状态：`frozen_pre_execution`

这是已完成 v1 运行门的版本化后续实验，明确排除 VIV。它要检验：Hamilton 的残差驱动、
受治理搜索控制，是否真正优于一次连续 PySR、匹配的重启/多 seed，以及从第一轮就拥有完整
算子集合的 PySR。

四个目标是：

1. 更低的终点公开验证 NRMSE；
2. 更高的 controller-only 真值恢复率和更低的灾难性失败率；
3. 用更少的引擎实测 evaluations 达到固定质量门槛，并取得更低 anytime AUC；
4. 将 DeepSeek token 和 wall-clock 额外成本限制在冻结上限内并完整报告。

修改前必须阅读 `PROTOCOL.md` 和 `dataset_split.yaml`。开发任务可以修复和调整 controller；
验证任务只用于选择一次最终策略；测试任务必须等代码、策略、指标、seed 和预算全部冻结后
才打开结果。测试结果不得再用于修改 v2 搜索策略。

生成数据、launch bundle、完整 workspace、checkpoint 和 provider 日志保持 Git 忽略；紧凑
结果、环境锁、报告和最终图表进入版本控制。
