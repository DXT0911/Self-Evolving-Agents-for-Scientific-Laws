# Hamilton 单风速单轮科学闭环验收

本任务验证 Hamilton 能否在一个轮次内完成 Discovery、Verification、Promotion 和
Finish。只研究 U248，不要求本轮发现最终 VIV 方程族。

## Phase 1 — Discovery

1. 读取 `task.md`、`plan.md` 和 `findings.md`。
2. 加载 `run-sr-experiment` Skill，并读取 `config_schema.md`。
3. 创建 `history/round1/experiment.json`，严格使用：
   - 原始输入：`input/U248_train.csv`；
   - `allowed_files` 只能包含该训练文件；
   - `max_rows=null`，读取完整训练序列；
   - `search_stride=5`，从完整 Discovery 区间均匀取样搜索；
   - 末尾20%为连续内部验证块；
   - 原始特征 `x,v`，目标 `a`，时间列 `t`；
   - PySR 运算符：二元 `+,-,*`，一元 `square,cube`；
   - `niterations=250`，`max_evals=8000`；
   - `populations=8`，`population_size=32`，`tournament_selection_n=12`；
   - `maxsize=31`，`parsimony=0.001`，`random_state=42`，`top_k=10`；
   - 5秒、500点短时 ODE，`state_limit=1000000`；
   - 候选科学重排开启，最多10个候选；
   - 权重：validation NRMSE 1.0、trajectory NRMSE 1.0、complexity 0.05；
   - ODE失败惩罚100；
   - 结果：`history/round1/results/viv-u248-single-round-v2.json`；
   - PySR目录：`history/round1/results/viv-u248-single-round-v2-pysr`。
4. 先 `--validate-only`，通过后执行一次正式搜索。

不得把已知 baseline 的项作为人工构造特征。结构和常数必须由 PySR 从原始 `x,v`
中搜索。不得读取任何 `*_test.csv` 或 OOD 文件。

## Phase 2 — Verification

读取结果 JSON，并至少检查：

- 实际读取行数、Discovery/内部验证时间范围和搜索抽样行数；
- `diagnostics.linear_raw_features`，并明确它仅为管线诊断；
- PySR 候选数量、所选方程、训练/验证 R²；
- 所选方法是否为 `scientific_score`；
- 每个候选的 ODE 状态、轨迹误差和科学评分；
- 所选候选是否真的优于简单诊断，以及能否支持 VIV 动力学结论。

## Phase 3 — Promotion

更新：

- `history/round1/trace.md`：配置、数据范围、候选表、诊断、验证和失败；
- `findings.md`：只写本轮证据支持的结论，区分“运行成功”和“科学成功”；
- `plan.md`：记录当前候选是否晋升、失败原因及下一轮具体策略。

证据不足时必须拒绝晋升，不得为了完成任务夸大结论。

## Phase 4 — Finish

调用 `finish(task_completed="true")`。message 必须包含 Discovery、Verification、
Promotion、Limitations 四个标题。这里的 true 表示该单轮验收流程完成，不表示方程
已经达到最终科研标准。
