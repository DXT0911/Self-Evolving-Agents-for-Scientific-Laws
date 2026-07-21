# Hamilton 单轮闭环验收

本任务只验收 Hamilton 能否在一轮内自主完成闭环，不评价方程的科研质量。

严格按以下顺序完成：

1. 阅读 `task.md`、`plan.md` 和 `findings.md`。
2. 加载 `run-sr-experiment` Skill。
3. 创建 `history/round1/experiment.json`，参数如下：
   - 只允许 `input/U248_train.csv`；
   - 前 2,000 行；
   - 末尾 20% 为连续内部验证块；
   - 特征为 `x`、`v`，目标为 `a`，时间列为 `t`；
   - `niterations=5`、`max_evals=200`；
   - `populations=4`、`population_size=12`、`tournament_selection_n=8`；
   - `maxsize=15`、`parsimony=0.01`、`random_state=42`、`top_k=5`；
   - 二元运算符为 `+ - * /`，无一元运算符；
   - 开启 1 秒、200 点的短时 ODE 验证；
   - 结果写入 `history/round1/results/closure-smoke.json`；
   - PySR 目录为 `history/round1/results/closure-smoke-pysr`。
4. 先调用标准 runner 的 `--validate-only`。
5. 验证通过后调用标准 runner 执行实验。
6. 阅读 `closure-smoke.json`。
7. 更新：
   - `history/round1/trace.md`：记录配置、执行状态、候选、指标和 ODE 状态；
   - `findings.md`：追加本轮经过验证的结论，并明确“不能形成科研结论”；
   - `plan.md`：更新当前冒烟候选、失败原因和下一步策略。
8. 调用 `finish`：
   - `task_completed="true"`；
   - `message` 必须概括 Discovery、Verification、Promotion 和结果局限。

禁止事项：

- 不得读取 `*_test.csv` 或 OOD 数据；
- 不得使用 `execute_bash`；
- 不得创建 Python 脚本；
- 不得重复已经成功的文件检查或 Skill 查询；
- 不得把低预算候选描述为 VIV 科学发现。
