# SR Agent 实验索引

这里的每个目录都是版本化实验包，应包含自己的研究问题、协议、manifest 或任务规范、
离线验证和紧凑报告。生成输入、launch bundle、checkpoint 和完整运行 workspace 均保持
本地忽略。

英文原文见 [`README.md`](README.md)。

## 当前实验

| 实验 | 状态 | 主要报告 |
|---|---|---|
| [`hamilton_vs_pysr_governed_search_v2/`](hamilton_vs_pysr_governed_search_v2/) | 排除 VIV 的冻结执行前 v2；新增完整算子基线、封存数据阶段和实测效率指标 | [`PROTOCOL.md`](hamilton_vs_pysr_governed_search_v2/PROTOCOL.md) |
| [`hamilton_vs_pysr_governed_search/`](hamilton_vs_pysr_governed_search/) | 公开 9-arm 运行门完成；正式多重复研究未运行 | [`OPERATIONAL_GATE_STATUS_2026-07-28.md`](hamilton_vs_pysr_governed_search/OPERATIONAL_GATE_STATUS_2026-07-28.md) |
| [`viv_dynamics_feedback_gate/`](viv_dynamics_feedback_gate/) | 不可执行准备态；等待独立授权 | [`PROTOCOL.md`](viv_dynamics_feedback_gate/PROTOCOL.md) |

已完成的运行门使用三个公开任务、一个重复，且没有访问 private/OOD。它只是先导信号，
不是普遍优越性的证据。冻结设计、事后离线诊断和剩余局限见实验 README。

## 实验包约定

新的正式实验应使用描述性目录，并分离以下职责：

```text
experiments/<experiment_id>/
├── README.md                当前状态与命令
├── PROTOCOL.md              冻结的科学比较契约
├── manifest/config/specs    机器可读冻结输入
├── test_*.py                离线契约测试
├── report.md/json           紧凑结果摘要
└── generated directories    本地忽略，绝不是源代码
```

观察结果后不得重写既有协议。修正或新增指标必须标为事后分析，或者在执行前放入新版本实验。
