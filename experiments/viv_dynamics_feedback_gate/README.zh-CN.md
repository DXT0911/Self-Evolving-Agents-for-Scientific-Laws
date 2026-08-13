# VIV 动力学反馈三臂公开运行门

状态：`frozen_authorized`。资源上限、环境预检、可执行配置和启动审计均须通过后方可运行。

本实验包冻结一个不可执行的公开 U248 单重复运行门，用于比较：

1. `direct_pysr`；
2. `fit_only_hamilton`；
3. `dynamics_aware_hamilton`。

它不复用 2026-07-28 运行门的授权、预算、manifest 或生成目录。当前没有可执行 launch
bundle，DeepSeek 与 PySR/Julia 权限均为 false，private/OOD 始终禁止。

## 文件

- `PROTOCOL.md`：冻结研究问题、公平边界、指标和停止规则。
- `preparation_manifest.yaml`：机器可读准备态与授权边界。
- `arm_specs.yaml`：三臂搜索期处理、共同终点评价和拟申请资源。
- `validate_preparation.py`：纯静态安全验证。
- `test_validate_preparation.py`：离线契约测试。

## 离线检查

```powershell
python -m experiments.viv_dynamics_feedback_gate.validate_preparation --mode launch
python -m experiments.viv_dynamics_feedback_gate.validate_launch_bundle
python -m unittest experiments.viv_dynamics_feedback_gate.test_validate_preparation
```

这些命令不调用 LLM、PySR 或 Julia，也不访问 private/OOD。任何启动前都必须先形成新的
授权记录、创建独立可执行配置和 launch bundle，并再次进行 launch 模式审计。
