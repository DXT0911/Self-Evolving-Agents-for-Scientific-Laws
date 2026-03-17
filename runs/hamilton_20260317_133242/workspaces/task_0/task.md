<!-- SRBENCH_ANCHOR_TASK_TEMPLATE -->
# Hamilton SRBench Task Template

本模板用于让 Hamilton 执行 OpenEvolve 风格的符号回归 benchmark 题，而不是当前仓库默认的 VIV ODE 任务。

## 工作约定

- workspace 根目录的 `candidate_model.py` 是当前最佳候选。
- 题目资产放在 `problems/<split>/<problem_id>/`。
- Python 相关命令统一使用 `./.venv/bin/python`，不要调用系统 `python3`。
- 本任务的比较对象是：`Hamilton` 与 `OpenEvolve` 在同一 problem pack、同一 evaluator 下的表现。
- 允许读取：
  - `initial_program.py`
  - `evaluator.py`
  - `config.yaml`
  - 训练相关输入文件
- 不允许修改 `problems/` 下原始题目文件。

## 每轮最低完成标准

1. 读取题目目录中的初始程序和 evaluator。
2. 在 formal search 中，每轮至少生成 3 个候选程序并保存到 `history/roundN/scripts/`。
3. 用 `./.venv/bin/python scripts/hamilton_srbench/select_best_candidate.py` 对这些候选做统一选优，并把最优者提升为 `candidate_model.py`。
4. 将本轮候选排名、当前 best score、有效改动和失败模式写入 `plan.md` / `findings.md`。

## PySR 使用要求

<!-- SRBENCH_ANCHOR_PYSR_PREFERENCE -->
- 对于非简单、非纯 smoke-test 的题目，优先用 PySR 做结构搜索或候选项筛选，再把结果翻译为 `candidate_model.py`。
- formal 5 轮搜索中，第 1 轮必须实际调用 PySR；若某轮停滞或退化，后续轮次应再次调用 PySR 或在 `findings.md` 明确说明为什么不调用。
- 如果本轮没有使用 PySR，必须在 `findings.md` 明确说明原因，例如：
  - 这轮只是 smoke test / 先验证 evaluator 链路
  - 任务过于简单，直接构造可解释结构更合适
  - 已有前轮 PySR 结果，本轮只做局部验证或程序化翻译

## 审查文件要求

<!-- SRBENCH_ANCHOR_AUDIT_RECORDS -->
- `task.md`：保留本次任务契约，不要删除或弱化
- `plan.md`：必须写清
  - 当前最佳候选方程
  - 当前最优分数
  - 与 `initial_program.py` 基线的比较
  - 本轮 3 个以上候选的排名摘要
  - 下一步策略
- `findings.md`：必须写清
  - 本轮候选方程
  - 本轮候选排名与被提升的理由
  - 是否使用 PySR
  - evaluator 输出的关键指标
  - 为什么当前改动有效或无效
  - 如果没有使用 PySR，原因是什么
<!-- SRBENCH_ANCHOR_FINDINGS_APPEND -->
- `findings.md` 追加规则：
  - 保留文件尾部的 `<!-- EVO_FINDINGS_APPEND -->`
  - 每轮写入时，用“新内容 + `<!-- EVO_FINDINGS_APPEND -->`”替换该锚点
  - 不要依赖 `insert_line` 在文件尾部追加，避免越界重试

<!-- SRBENCH_ANCHOR_SMOKE_FINISH -->
## Smoke Test 停止规则

- 如果当前任务明确写了 `smoke test`，那么在第一次成功运行 evaluator 并完成 `plan.md` / `findings.md` 更新后，必须立即调用 `finish(task_completed="true")`。
- smoke test 不做额外 EDA，不调用额外 helper script，不为“更漂亮的计划文件”继续消耗回合。

## 输出契约

`candidate_model.py` 必须定义：

```python
def func(x, params):
    ...

def run_search():
    return func
```

## 备注

- 如果 benchmark staging 目录中未提供测试/OOD文件，则表示这些资产被故意隐藏，最终评估需在外部完成。
- 如果要做和 OpenEvolve 的正式对比，运行期 train score 只作过程记录；最终对比应使用统一的外部 post-evaluation。
- 如果任务要求“5 轮搜索”，则 round 1~4 不得提前结束任务；应在第 5 轮完成记录后再允许 `task_completed="true"`。
