# 治理搜索实验运行门报告——2026-07-28

本文记录三个公开任务、每个任务一个配对重复的运行验证结果。它是运行门先导实验，不是正式基准实验结论。

## 1. 完成范围

- 任务：`static_s01`、`dynamic_d01`、`viv_u248`
- 重复：均为 `repeat_1`
- 实验臂：治理式 Hamilton、ordinary PySR、fixed-schedule PySR
- 完成实验臂：9/9
- private/OOD 访问：无
- PySR/Julia requested evaluations：108,000/108,000
- DeepSeek tokens：2,751,149/3,600,000
- Git 基准提交：`b87800bcdcf3d2a1e4dd4548b7a63a5d52c3e147`

Hamilton 先运行并确定动态预算，两个 PySR 基线随后复现同一累计预算：

| 任务 | Hamilton 实际日程 | 分轮 seeds | 每个实验臂总预算 |
|---|---|---|---:|
| `static_s01` | 4,000 / 4,500 / 3,500 | 1101 / 1102 / 1103 | 12,000 |
| `dynamic_d01` | 4,000 / 4,500 / 3,500 | 1101 / 1102 / 1103 | 12,000 |
| `viv_u248` | 4,000 / 5,000 / 3,000 | 1101 / 1102 / 1103 | 12,000 |

三条预算轨迹已冻结在
`launch_bundle/paired_budget_traces/<task>/repeat_1.json`。

## 2. 终点结果

NRMSE 和 scientific score 越低越好。fixed-schedule PySR 的结果取三个冻结分段中 scientific score 最低的候选。

### `static_s01`

| 实验臂 | 验证 NRMSE | 验证 R² | Scientific score | 复杂度 |
|---|---:|---:|---:|---:|
| 治理式 Hamilton | 0.08031254 | 0.99354990 | 0.09656254 | 13 |
| ordinary PySR | 0.13784793 | 0.98099795 | 0.17494470 | 23 |
| fixed-schedule PySR | **0.00048692** | **0.99999976** | **0.03435789** | 21 |

Hamilton 优于 ordinary PySR，但明显落后于 fixed-schedule PySR。fixed-schedule 的 seed 1102 候选接近该 AI Feynman 任务的参考结构，说明这个任务上的重启/seed 效应强于 Hamilton 当前的配置干预。

### `dynamic_d01`

| 实验臂 | 验证 NRMSE | 验证 R² | Scientific score | 复杂度 |
|---|---:|---:|---:|---:|
| 治理式 Hamilton | **0.35508779** | **0.87391266** | **0.38953223** | 31 |
| ordinary PySR | 0.56806614 | 0.67730086 | 0.60516292 | 23 |
| fixed-schedule PySR | 0.64653200 | 0.58199637 | 0.68201587 | 22 |

Hamilton 同时优于两个基线。主要改进来自第三轮把 `tanh` 加入 unary operators；验证 R² 从前两轮的 0.447、0.660 提升到 0.874。残差 lag-2 自相关仍为 0.703，略高于预注册的 0.70 门槛，因此没有通过最终科学成功门。

这里的 `tanh` 是 Hamilton 的自适应搜索控制干预。所有实验臂共享相同初始搜索配置，但基线保持固定，Hamilton 可以在 trust-region 内改变一个配置字段；该差异是实验处理本身，而不是完全相同的终点搜索空间。

### `viv_u248`

| 实验臂 | 验证 NRMSE | 短期轨迹 NRMSE | 验证 R² | Scientific score | 复杂度 |
|---|---:|---:|---:|---:|---:|
| 治理式 Hamilton | 0.68720010 | **0.43869686** | 0.52775603 | **1.13689695** | 11 |
| ordinary PySR | **0.68718180** | 0.48425727 | **0.52778118** | 1.17627778 | 3 |
| fixed-schedule PySR | **0.68718180** | 0.48425727 | **0.52778118** | 1.17627778 | 3 |

Hamilton 的综合 score 较低，原因是短期轨迹 NRMSE 改善；它的点值验证 NRMSE 和 R² 反而极轻微地差于两个基线，而且表达式更复杂。三轮都没有发现速度依赖，最终方程仍接近线性恢复力：

`a = -161.242987983945*x - 7.2266703`

因此，VIV 结果只能称为短期轨迹评分上的小幅改进，不能称为发现了更完整的 VIV 动力学。

## 3. 配对胜负摘要

按每个任务最终 scientific score：

- Hamilton 对 ordinary PySR：3 胜 / 0 负；
- Hamilton 对 fixed-schedule PySR：2 胜 / 1 负。

按纯验证 NRMSE：

- `static_s01`：Hamilton 胜 ordinary、负 fixed-schedule；
- `dynamic_d01`：Hamilton 胜两个基线；
- `viv_u248`：Hamilton 轻微负于两个基线。

因此，当前最准确的描述是：

> 在三个预注册公开任务、每个任务一个重复的运行门中，治理式 Hamilton 在综合 scientific score 上显示正信号，尤其在 `dynamic_d01` 上产生了有效的搜索空间干预；但结果混合、任务依赖明显，尚不能证明总体改进、跨重复稳定性或更高预算效率。

## 4. 不能从本次实验得出的结论

1. 每个任务只有一个 repeat，不能评价跨重复稳定性、方差或置信区间。
2. 不能声称 Hamilton 普遍优于 PySR。
3. 不能声称 Hamilton 恢复了 `dynamic_d01` 的真实方程；controller 侧真值等价验证器尚未实现。
4. 不能声称发现了完整 VIV 动力学；没有速度依赖，也没有长期动力学或 private/OOD 证据。
5. 不能严格声称更高的 evaluation 效率；当前缺少实际消耗和 anytime 轨迹。

## 5. 运行门发现的基础设施与协议问题

### Evaluation 测量

runner 记录的是请求的 `max_evals` 预留额度，而不是 PySR 报告的实际 evaluation 数量。108,000 表示匹配的搜索上限和 controller 记账请求，不是独立测量的引擎实际消耗。

当前也没有输出最佳结果随 cumulative evaluations 变化的轨迹，因此无法计算预注册的 anytime AUC。

### 真值验证

`static_s01` 和 `dynamic_d01` 的来源数据具有参考方程，但仓库尚未实现 controller 侧参考方程注册表、代数等价验证和独立挑战网格，故 `equivalent_ground_truth` 仍未确定。

### LLM 资源与恢复

- `static_s01` Hamilton：1,047,805 tokens
- evaluation 前无效尝试：139,005 tokens
- `dynamic_d01` Hamilton：939,099 tokens
- `viv_u248` Hamilton：625,240 tokens
- 合计：2,751,149 tokens

`dynamic_d01` 暴露了 Windows 前台终端超时后 stdout 管道关闭的问题。Python 进程继续运行时，日志输出触发 `OSError 22`，造成 Promotion 无效重读和额外 token 消耗。后续改用隐藏后台进程和持久 stdout/stderr 文件后问题消失。

为了完成运行门，Discovery 和 Promotion 单阶段 token 上限从原先的 80,000/95,000 修订为 160,000/160,000。这不改变任何 PySR evaluation 配额，但属于运行中资源配置修订，正式研究必须在启动前重新冻结。

### Agent 协议偏差

`viv_u248` 首轮 LLM 在通用先验中写入了振子方程示例。它没有访问隐藏答案，也没有改变冻结的 Round 1 PySR 配置，但违反了“先验只记录定性机制、不写方程语法”的提示约束。正式研究前应让 controller 对该块执行机器校验，而不是仅依赖提示词。

## 6. 运行门裁决

九个实验臂均产生了结构有效的公开结果，三条 evaluation 账本都严格收敛到 12,000，seed、数据哈希和 private/OOD 隔离未被破坏。

但是，在进入正式多重复 benchmark 之前，至少应完成：

1. 记录实际 PySR evaluations 和 best-so-far 曲线；
2. 实现 anytime AUC；
3. 实现已知真值任务的 controller 侧等价验证；
4. 修复或机器拒绝先验块中的方程泄露；
5. 冻结新的 Discovery/Promotion token 配置；
6. 使用后台持久日志作为标准启动方式。

在这些问题解决前，本次结果应保持为“有正信号的运行门先导实验”，而不是正式效果证明。
