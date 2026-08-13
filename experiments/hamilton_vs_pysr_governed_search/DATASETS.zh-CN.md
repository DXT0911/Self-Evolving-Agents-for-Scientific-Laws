# 数据集选择与获取计划

英文原文见 [`DATASETS.md`](DATASETS.md)。如中英文解释出现差异，以冻结英文计划和机器可读
manifest 为准。

## 选择原则

Benchmark 必须区分搜索控制能力与 VIV 特定可辨识性。只有满足以下条件的任务才纳入：

- 数据公开，来源和许可证可追溯；
- 能由当前标量符号回归 runner 表示，或只需小型预注册 adapter；
- 所有实验臂可使用相同 features、target、划分、搜索空间和 evaluator；
- 不需要 private/OOD 访问；
- 有足够行数进行 discovery/validation 划分；
- 不向 Agent 暴露真值方程。

若任务需要 PDE 发现、图像/文本输入、无界分类变量处理、缺少 target 定义，或要求在 pilot
期间新增大型多方程 controller，则排除。

## 家族 A：盲测静态已知真值任务

候选来源：

- AI-Feynman Symbolic Regression Database：
  `https://space.mit.edu/home/tegmark/aifeynman.html`
- 标准化 PMLB/SRBench 版本：
  `https://github.com/EpistasisLab/pmlb` 和
  `https://github.com/cavalab/srbench`

六个 pilot 标识冻结在 PMLB revision
`7c1f4bdc00136dc2e55c87fa6b8ba6e8af6d1a68`：

| 不透明任务 | PMLB 源 ID | 结构类别 |
|---|---|---|
| `static_s01` | `feynman_I_14_4` | 多项式交互 |
| `static_s02` | `feynman_I_12_2` | 多变量有理式 |
| `static_s03` | `feynman_II_15_4` | 周期/三角函数 |
| `static_s04` | `feynman_I_6_2a` | 指数 |
| `static_s05` | `feynman_I_18_4` | 混合有理式 |
| `static_s06` | `feynman_III_9_52` | 困难的周期/有理混合 |

这些标识在任何 Hamilton/PySR pilot 结果出现前选定。数据字节从固定 Git LFS revision
下载到被忽略的 `data_cache/`；大小和 SHA-256 指纹冻结在 `pilot_manifest.yaml`。行数、
feature 映射和公开划分 adapter 仍需验证。确定性 nuisance-variable 变换只能作为单独版本
任务加入，不能静默替换这六个输入之一。

为降低 LLM 记忆泄漏：

- 向 Agent 展示的任务 ID 和变量均为不透明标识；
- 移除方程名称和物理章节标签；
- 参考表达式只保留在 controller 侧；
- 主要盲测轨道不提供公式特定的文献上下文。

## 家族 B：已知真值动力学导数

主要候选来源：

- ODE-Strogatz：`https://github.com/lacava/ode-strogatz`

公开来源把二状态非线性 ODE 系统的每个导数分别表示为回归任务。四个 pilot 标识冻结在同一
PMLB revision：

| 不透明任务 | PMLB 源 ID | 结构挑战 |
|---|---|---|
| `dynamic_d01` | `strogatz_vdp1` | 三次非线性交互 |
| `dynamic_d02` | `strogatz_barmag1` | 耦合三角项 |
| `dynamic_d03` | `strogatz_glider2` | 除法与三角项 |
| `dynamic_d04` | `strogatz_shearflow2` | 混合三角乘积 |

每个任务从两个状态变量中发现一个导数。在禁用 ODE rollout 时，它与当前标量回归 runner
兼容。它检验动力学数据上的符号恢复，但本身不检验联合轨迹或吸引子恢复。Pilot 不引入
联合多方程发现；这属于未来单独实验。

## 家族 C：公开 VIV

Pilot 任务：

```text
playground/hamilton/workspace/input/U248_train.csv
```

扩展候选：

- `U254_train.csv`
- `U260_train.csv`
- `U273_train.csv`
- `U282_train.csv`

只有公开训练文件符合条件，继续使用现有连续尾段验证规则。私有配对初始条件、held-out
test 和外部工况文件不属于获取或分析范围。

五个风速构成一个相关 VIV 家族，不能计作五个独立 benchmark 领域。

## 获取状态

十个外部输入已经从 PMLB revision
`7c1f4bdc00136dc2e55c87fa6b8ba6e8af6d1a68` 获取到本地。缓存有意由 Git 忽略，已提交的
manifest 是完整性锁。VIV U248 已是版本化公开输入。

启动前，adapter 准备仍必须：

1. 校验 gzip 完整性、行数、有限数值列和 target 映射；
2. 生成确定性公开训练/验证划分；
3. 生成 Agent 可见的不透明 metadata；
4. 将参考方程保留在运行 workspace 外；
5. 验证没有路径或 manifest 条目指向 private/OOD 资产。
