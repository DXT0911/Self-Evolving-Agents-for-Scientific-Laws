# Hamilton 可部署 Agent 设计思路

日期：2026-08-17
状态：设计草案（待定稿）

## 1. 目标与用户画像

把 Hamilton 从"研究框架"变成"别人能拿来就用的符号回归 Agent"。

- **用户**：研究者/工程师，有自己的数据，想自动发现一个可解释的符号方程，不关心 PySR/LLM 的内部细节。
- **核心场景**：丢进一个 CSV → 跑出一个方程 + 可信度证据。
- **非目标**：不要求用户懂 Julia、懂 controller、懂 token 预算；这些对用户透明。

## 2. 黄金路径（用户视角，只记这一条）

```bash
# ① 部署（一条命令，二选一）
pip install hamilton-agent        # 或
docker run -it hamilton/agent     # Docker 打包了 Julia+PySR，最省事

# ② 准备数据 + 一个最小配置
#    mydata.csv：列名 x1,x2,x3（特征）、y（目标）、t（可选时间/排序）
#    mytask.yaml：
#      data: mydata.csv
#      features: [x1, x2, x3]
#      target: y
#      time_column: t

# ③ 运行
hamilton discover --config mytask.yaml

# ④ 拿结果
#    output/equation.md   ← 发现的方程（sympy 简化，人可读）
#    output/report.md     ← 证据 + 可读推理（plan/findings 风格）
#    output/evidence.json ← 机器可读（score/残差/复现信息）
```

用户只需要知道：**数据在哪、哪列是目标、跑一条命令、去哪读方程。**

## 3. 数据接口（统一、零摩擦）

当前数据分散在 `task_specs.yaml` + `prepared_data/` + 各种 config 里。要收敛成一个接口：

| 用户提供 | 系统自动做 |
|---|---|
| CSV 文件 | 列名校验、数值类型、缺失值检查 |
| 特征列名 + 目标列名 | 自动 train/validation split（连续时间块，避免泄漏） |
| 可选 time 列（动力学任务） | 自动标准化、search stride、残差诊断 |
| 可选 task 类型（static / dynamic / ode） | 自动选验证器（点值 NRMSE / 轨迹 / 长期动力学） |

**设计原则**：给用户一个"声明式"配置（只声明数据和列名），其余（算子集、预算、验证器）走冻结的默认值；高级用户再往下开洞自定义。

## 4. 部署方案（解决最重的依赖）

Hamilton 最重的依赖是 **Julia + PySR**（首装要编译数分钟、体积大）。两条路：

1. **Docker 镜像（推荐）**：`Dockerfile` 打包 Python + Julia + PySR + EvoMaster。用户 `docker run` 即用，不用碰本地环境。数据通过 volume 挂载进去。
2. **pip 包**：`pyproject.toml` 把 `evomaster/` + `playground/hamilton/` + `skills/` 打包成 `hamilton-agent`，PySR/Julia 作为可选依赖（或由用户自装）。

API key 用 `.env` 或环境变量 `HAMILTON_API_KEY`，镜像里绝不硬编码。

## 5. 输出（"跑出方程"要交付什么）

一个 run 产出三个文件，各司其职：

- **`equation.md`**：发现的最优方程（`y = 0.5*x1*x2^2 + ...`），加上复杂度、validation R²/NRMSE。
- **`report.md`**：可读推理链——每轮做了什么、为什么改配置、残差诊断发现了什么（就是现在 HCC 的 plan.md/findings.md 的内容，整理成人话）。
- **`evidence.json`**：机器可读的完整证据（score、engine evals、token、seed、数据 hash、git commit、模型名），保证**可复现**。

## 6. 架构改动（把研究框架产品化）

现在的 `run.py --agent hamilton` 是通用入口，需要收敛成一个 hamilton 专用入口：

```
hamilton discover --config mytask.yaml
        │
        ├─ 数据层：读 mytask.yaml → 校验 CSV → 生成冻结 runner config + workspace
        ├─ 引擎层：HCC 混合循环（自由 LLM 决策 + 可读记忆 + 配对对照）
        │           └─ 复用现有 playground.py + run_experiment.py + skills
        └─ 输出层：打包 equation.md + report.md + evidence.json
```

关键是把三件事从研究脚本里"抽"出来，变成稳定接口：
1. **数据 → 任务** 的转换（`task_specs.yaml` 的手工流程 → 自动配置生成）。
2. **run → 报告** 的转换（`collect_pilot.py` 的手工汇总 → 自动报告模板）。
3. **依赖 → 镜像** 的打包（Dockerfile + pyproject.toml）。

## 7. 复现保证（别人能信这个方程）

每个输出都带一份"复现快照"：

```text
git commit + config + 数据 sha256 + seed + 模型名 + 环境版本
```

任何人拿到 `evidence.json` 里的这串信息，就能重跑出同一个方程。这正是 `RESEARCH_PROTOCOL.zh-CN.md` 里已经写死的要求，只是现在要自动化进输出。

## 8. 分阶段实现

- **Phase 1（最小可用）**：`hamilton discover` CLI wrapper + 数据接口（mytask.yaml → config）+ 结果打包（equation/report/evidence）。核心引擎先用现有的混合 HCC 循环。
- **Phase 2（易部署）**：Dockerfile + pyproject.toml + `.env` 密钥管理 + 一键安装文档。
- **Phase 3（易复现）**：示例数据集 + 复现快照自动化 + 一个"从零到方程"的 5 分钟教程。

## 9. 与当前研究的关系（避免冲突）

- 产品化**不改变**研究主线：混合 HCC 循环仍是引擎，配对对照/测量纪律仍在研究侧跑。
- 产品化的"默认配置"就是研究侧验证过的冻结配置；研究侧新增的实验（如 10-seed 消融）不进入产品默认路径。
- 两条线独立：研究继续在 `experiments/` 下迭代，产品化在 `hamilton discover` 这条稳定入口上收敛。

## 10. 关键取舍（需要你拍板）

1. **引擎选哪条**：产品默认用混合 HCC（自由 LLM + 可读记忆），还是也提供"确定性 controller 模式"（更便宜、可复现但少推理）给预算敏感的用户？建议两者都要，默认 HCC。
2. **模型**：默认用 deepseek-v4-pro（强）还是 v4-flash（便宜）？建议暴露成 config 让用户选，默认 pro。
3. **部署优先 Docker 还是 pip**：建议 Docker 优先（解决 Julia 编译痛点）。
