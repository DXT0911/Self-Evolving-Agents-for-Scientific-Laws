# 研究计划

## 任务
Solve problems/phys_osc/PO10 with a formal 5-round Hamilton search. This is not a smoke test. In round 1 you must actually use PySR. In every round generate at least three candidate program files under history/roundN/scripts, rank them with ./scripts/hamilton_srbench/select_best_candidate.py on problems/phys_osc/PO10, promote only the best to candidate_model.py, and record the ranking plus rationale in plan.md and findings.md. Return task_completed='false' in rounds 1-4. In round 5, after recording the final best candidate and next-step conclusions, you may return task_completed='true'.

<!-- EVO_CURRENT_BEST_BEGIN -->
## 当前最优
- 轮次：5
- 方程：y = a * x^2 / (1 + g * t^2) + b * cos(c*t + d) + e + f * sin(x) / (1 + h * t^2)
- 训练 MSE：77.2850（combined_score ≈ -1.88810）
- 来源：round5 candidate_b（将 tanh 修正线性化为 sin(x)/(1+h t^2)，在保持稳定的同时略降误差与简化参数）
- 更新时间：本轮
<!-- EVO_CURRENT_BEST_END -->

## 数据概览
（首轮 EDA 后填写：变量列表、基本统计、初步观察）

- 列：x (位置), t (时间)
- 目标变量：dv_dt（非线性振子加速度）
- 数据规模：4000 行 × 2 列；y 向量长度 4000
- 统计：x ∈ [-7.81, 7.54]，t ∈ [-1.11, 1.14]，y ∈ [0.0, 36.0]，y 均值 ≈ 17.91
- 缺失值：无（npy 加载正常）
- 显著模式：PySR 暗示 y ≈ x^2 + f(t)，f(t) 包含 cos(t) 成分；sin(x/t) 在部分表达式中出现，但主导项为 x^2 与 cos(t) 的线性叠加

## 当前假设
（Agent 基于数据探索填写——可能存在什么方程/关系？）

1. dv_dt ≈ α x^2 + β cos(ω t + φ) + c
2. 次要修正项可能包含 sin(x/t) 或 cos(cos(t)) 等小幅度谐波，但影响较小
3. 物理直觉：非线性势（如 V ∝ x^3 或 x^4）可导致加速度与 x^2 成分相关，外载或时变项通过 cos(t) 体现

## 已确认知识
- 相关变量：x, t（均有显著贡献）
- 已发现的关键关系：x^2 与 cos(t) 的组合能显著降低 MSE

## 策略队列
<!-- EVO_STRATEGY_QUEUE_BEGIN -->
1. Round 2：基于 PySR 结果，加入双频 cos 结构与小幅 sin(x/t) 项的候选，进一步网格搜索初始点（多重 restart）
2. Round 3：尝试模板化结构：y = a(x) + b(t)，分别用低复杂度表达式逼近；并引入安全的分式项 x^2/(1+γ t^2)
3. Round 4：若收敛停滞，重新使用 PySR（增加 niterations 与运算符，如 tanh、abs）缩小搜索窗口
4. Round 5：做简化与稳健性分析，选择最简且得分相当的表达式
<!-- EVO_STRATEGY_QUEUE_END -->

## 失败方法
| 轮次 | 策略 | 变量 | 模板/参数 | MSE | 失败原因 |
|------|------|------|-----------|-----|----------|
