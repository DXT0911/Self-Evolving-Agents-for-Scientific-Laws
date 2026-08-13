# Hamilton 自适应多轮研究验收

使用 U248 训练数据作为测试基准，验证 Hamilton 能否根据上一轮证据自行设计下一轮，
而不是验证某个预先写死的 VIV 专用算法。最多运行3轮。

## 数据边界

- 研究数据只能使用 `input/U248_train.csv`。
- 搜索和选择期间不得读取测试集或 OOD 数据。
- 输入保持为原始变量 `x,v`，目标为 `a`，不得把已知参考方程的项构造成输入特征。

## 第1轮基线

第1轮使用以下配置：

- 完整训练文件：`max_rows=null`，`search_stride=5`；
- 连续末尾20%内部验证；
- 二元运算符 `+,-,*`，一元运算符 `square,cube`；
- `niterations=250`，`max_evals=8000`；
- `populations=8`，`population_size=32`，`tournament_selection_n=12`；
- `maxsize=31`，`parsimony=0.001`，`random_state=42`，`top_k=10`；
- 短时 ODE：5秒、500点、`state_limit=1000000`；
- 候选重排权重：validation NRMSE 1.0、trajectory NRMSE 1.0、
  complexity 0.05，失败惩罚100；
- 结果写入 `history/round1/results/adaptive-round-1.json`。

## 后续轮次

第 N 轮必须读取上一轮写入 `plan.md` 的下一轮实验契约，并且：

1. 只改变一个主要实验因素；
2. 使用 schema 已支持的配置字段；
3. 使用新的 experiment ID 和 `history/roundN/` 输出；
4. 明确检验上一轮的原因假设；
5. 将结果与上一轮证据比较；
6. 未达到总体科研标准时写出新的下一轮契约并
   `finish(task_completed="false")`。

允许的单轮预算上限：

- `niterations <= 1000`；
- `max_evals <= 20000`；
- ODE `duration <= 60` 秒；
- `top_k <= 10`。

## 总体科研成功标准

只有同时满足以下条件才允许 `task_completed="true"`：

1. 候选结构和系数来自原始变量的符号搜索，不是人工写入参考结构；
2. 候选通过内部连续验证，并给出与诊断基线的定量比较；
3. 候选的任务相关动力学解释得到 rollout 证据支持，而不是只依赖瞬时 R²；
4. `findings.md` 清楚记录可复现证据和仍然存在的限制；
5. 没有因为达到最大轮数而把未满足标准描述成成功。

本验收的主要对象是跨轮自适应行为。即使3轮后仍未得到满意方程，只要每轮完整闭环、
配置发生有证据驱动的实质变化、L2持续积累且停止信号诚实，也属于多轮机制验证成功。
