# Hamilton vs PySR v2：operational gate 结果

状态：八个运行全部完成。这里只包含两个任务、一个重复，是工程运行门和反证实验，
不是最终论文结论。当前策略不应直接进入 validation calibration 或 sealed test。

## 本科生版结论

每个方法得到相同的 12,000 requested evaluations。Hamilton 把额度分成
4,000 / 4,500 / 3,500 三轮，并在轮间让 DeepSeek 根据验证与残差结果修改一个
搜索参数。三个 PySR 对照分别测试：一次连续搜索、只分段但不调参、分段且从一开始
拥有更宽的算子集合。

| 任务 | 方法 | 验证 NRMSE（越低越好） | 验证 R²（越高越好） | DeepSeek token |
|---|---|---:|---:|---:|
| static_s02 | ordinary PySR | 0.4402 | 0.8062 | 0 |
| static_s02 | fixed schedule | 0.4256 | 0.8189 | 0 |
| static_s02 | union schedule | **0.2364** | **0.9441** | 0 |
| static_s02 | Hamilton | 0.2588 | 0.9330 | 512,899 |
| dynamic_d02 | ordinary PySR | **0.0583** | **0.9966** | 0 |
| dynamic_d02 | fixed schedule | 0.0959 | 0.9908 | 0 |
| dynamic_d02 | union schedule | 0.4257 | 0.8188 | 0 |
| dynamic_d02 | Hamilton | 0.2380 | 0.9434 | 889,112 |

没有任何方法精确恢复 controller 中登记的真实方程。引擎实测 evaluations 因初始化和
批处理会略高于 requested evaluations；完整数值与 anytime 曲线见公开证据 JSON。

## 这说明什么

Hamilton 目前不是稳定优于普通 PySR。它在静态任务上胜过普通与固定分段 PySR，说明
闭环调参有潜力；但更宽的 union 对照略胜 Hamilton。在动态任务上，一次连续 PySR
最好，固定分段第二，Hamilton 第三。这表明当前最急迫的问题不是增加 LLM 额度，而是：

1. 三轮重启会丢失一次连续搜索积累的种群和候选；
2. Hamilton 把 `maxsize` 从 31 提到 41、再提高 `parsimony`，两次都没有改进 incumbent；
3. 残差证据很强，但从残差到“改哪个参数”的策略不够可靠；
4. Promotion 审计曾因格式错误反复消耗 token，虽然已加入确定性修复后的快速闭合。

## 下一步建议

先开发 v3 策略，不打开 sealed test：让 Hamilton 在轮间延续 PySR search state，或给
ordinary PySR 一个同样可延续的公平对照；把“保持配置继续搜索”作为允许动作；在
static_s02、static_s04、dynamic_d02、dynamic_d03 上做至少三个重复后再选择策略。
对动态任务应增加一种预先声明的候选策略：当训练/验证分布明显非平稳且 lag-1 残差
接近 1 时，不根据单次残差直接增大表达式复杂度。

可复现入口：

- `public_evidence/operational_gate_v2/README.md`
- `public_evidence/operational_gate_v2/analysis/operational_gate_summary.csv`
- `analyze_operational_gate.py`
- `freeze_paired_budget.py`
