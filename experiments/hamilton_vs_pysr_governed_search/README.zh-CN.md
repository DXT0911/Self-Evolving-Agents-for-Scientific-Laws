# Governed Hamilton 与固定 PySR 对照实验

本目录保存当前 governed Hamilton 搜索 controller 与固定 PySR 搜索的预注册方案和离线
准备设施。英文原文见 [`README.md`](README.md)。

## 当前状态

`public_operational_gate_completed`

三个任务、一个重复的公开运行门已经完成全部九个实验臂。Hamilton 先运行，两个基线随后
获得其冻结的实际预算轨迹。过程中没有访问 private/OOD。结果是包含混合正信号的运行
pilot，不是完整的正式多重复 benchmark，也不能证明普遍优越性。

紧凑中文报告见
[`OPERATIONAL_GATE_STATUS_2026-07-28.md`](OPERATIONAL_GATE_STATUS_2026-07-28.md)。
`arm_contracts.yaml` 中保留的 `frozen_waiting_authorization` 描述执行前冻结契约，是历史契约
元数据，不是当前实验状态。运行门授权已经用完，不授权任何后续 DeepSeek 或 PySR/Julia
执行。

本实验不是旧 Hamilton 消融，首要问题是：

> 在相同公开数据、初始 PySR 搜索空间、累计 evaluation 预算、候选 evaluator 和配对 seed
> 计划下，治理式 LLM 搜索控制能否在验证质量、重复稳定性和 evaluation 效率上优于固定
> PySR？

## 文件

- [`PROTOCOL.zh-CN.md`](PROTOCOL.zh-CN.md)：假设、实验臂、公平规则、指标和分析计划。
- [`DATASETS.zh-CN.md`](DATASETS.zh-CN.md)：benchmark 家族、纳入规则、隔离和获取计划。
- `pilot_manifest.yaml`：机器可读的准备状态和 pilot 设计。
- `arm_contracts.yaml`：冻结的授权边界和实验臂允许差异。
- `result_record.schema.json`：每个重复的紧凑结果契约。
- `prepare_public_data.py`：校验哈希并产生不透明公开 CSV 输入的 adapter。
- `task_specs.yaml`：冻结任务 adapter 和共享初始数值搜索空间。
- `build_launch_bundle.py`：不执行实验，只生成被忽略的 99-job launch bundle。
- `freeze_paired_budget.py`：冻结一条 Hamilton 账本，生成两个配对 PySR replay 配置，不复制
  科学输出。
- `validate_launch_bundle.py`：离线审计所有 runner 配置和任务数据。
- `validate_manifest.py`：离线准备/启动就绪验证器。
- `evaluation_curves.py`：重建已完成 episode 边界的 evaluation 曲线；至少存在两个边界时，
  计算预算加权 anytime AUC。
- `controller_ground_truth.yaml`：仅 controller 可见的参考方程和确定性 challenge grid；
  绝不能进入 Agent workspace。
- `ground_truth_equivalence.py`：对 controller-only 注册表进行代数、数值和变量选择等价检查。
- `collect_ground_truth_equivalence.py`：对 launch bundle 中每个已完成公开结果边界应用等价检查。
- `test_*.py`：离线契约测试。

## 离线评价工具

以下命令不会导入或调用 PySR、Julia 或 LLM，也不会访问 private/OOD：

```bash
python -m experiments.hamilton_vs_pysr_governed_search.evaluation_curves
python -m experiments.hamilton_vs_pysr_governed_search.ground_truth_equivalence \
  static_s01 --result path/to/result.json
python -m experiments.hamilton_vs_pysr_governed_search.collect_ground_truth_equivalence
```

由于旧 pilot 没有记录引擎实测的逐 evaluation 时间戳，曲线工具使用累计“请求”
evaluations 和已完成 round/episode 边界。ordinary PySR 的一次性终点结果只含一个值，
其 anytime AUC 为 `null`，不会被包装成 anytime 轨迹。等价工具将代数判定和严格的
controller-only challenge-grid 判定分开。VIV 因没有唯一注册真值方程而明确标记为不适用。

对于已完成 pilot，这些定义属于事后探索诊断：插值规则、challenge grid 和容差在观察结果
后才加入。如需在后续重复中支持验证性结论，必须在运行前冻结。

## 离线验证

以下命令只解析本地 YAML 并执行静态检查：

```powershell
python -m unittest experiments.hamilton_vs_pysr_governed_search.test_validate_manifest
python -m unittest experiments.hamilton_vs_pysr_governed_search.test_prepare_public_data
python -m unittest experiments.hamilton_vs_pysr_governed_search.test_build_launch_bundle
python experiments/hamilton_vs_pysr_governed_search/build_launch_bundle.py
python experiments/hamilton_vs_pysr_governed_search/validate_launch_bundle.py
python experiments/hamilton_vs_pysr_governed_search/validate_manifest.py `
  experiments/hamilton_vs_pysr_governed_search/pilot_manifest.yaml `
  --mode preparation
```

准备阶段预期不能通过启动就绪验证：

```powershell
python experiments/hamilton_vs_pysr_governed_search/validate_manifest.py `
  experiments/hamilton_vs_pysr_governed_search/pilot_manifest.yaml `
  --mode launch
```

这种失败是安全属性，不是实验失败。

被忽略的公开源缓存存在后，可以在不使用 LLM、PySR 或 Julia 的情况下重建不透明输入：

```powershell
python -m experiments.hamilton_vs_pysr_governed_search.prepare_public_data `
  experiments/hamilton_vs_pysr_governed_search/pilot_manifest.yaml
```

## 后续运行前必须重新决策

任何新增重复或扩展任务集合都属于新的执行决策。开始前必须：

1. 冻结任务/重复范围和新的累计 PySR evaluation 预算。
2. 若将事后 AUC 与等价定义用作验证性指标，在观察新结果前冻结它们。
3. 为新范围分别授权 DeepSeek 与 PySR/Julia。
4. 除非后续 Tier 决策获得独立授权，继续禁止 private/OOD 访问。

配对规则仍为 Hamilton → 冻结额度和 seed → ordinary PySR 与 fixed-schedule PySR。
已完成运行门每个任务使用 12,000 上限和冻结 manifest 中记录的动态边界；这些已消耗额度
不能被默认为后续运行授权。

十个外部 pilot 输入已在固定 PMLB revision 上选定、下载，并在 `pilot_manifest.yaml` 中
记录指纹。其字节保存在 Git 忽略的 `data_cache/`；VIV U248 引用现有版本化公开 workspace
输入。

Private test/OOD 数据不属于本实验范围。
