# Hamilton - 符号回归 Agent

Hamilton 是基于 EvoMaster 框架的符号回归（Symbolic Regression）Agent，专门用于在**过完备变量**环境下发现数学方程。

协作修改前阅读 [`DEVELOPMENT.zh-CN.md`](DEVELOPMENT.zh-CN.md)（英文原文：
[`DEVELOPMENT.md`](DEVELOPMENT.md)）；科学与数据隔离规则以
[`../../docs/sragent/RESEARCH_PROTOCOL.zh-CN.md`](../../docs/sragent/RESEARCH_PROTOCOL.zh-CN.md)
为准；当前配置和历史配置的状态见
[`../../configs/hamilton/README.zh-CN.md`](../../configs/hamilton/README.zh-CN.md)。

## Benchmark 隔离

- Agent 只读取运行 workspace 中的公开 `task.md`、`plan.md` 和 `findings.md`。
- 参考方程、系数、目标标签和 sealed test/OOD 资产保存在 workspace 外的
  `benchmarks/<name>/private/`，该目录被 Git 忽略且不得提交。
- LLM 文件工具被限制在 active workspace，不能通过绝对路径读取私有 benchmark。
- 第一轮先使用 `literature-grounding` 和 `literature_search` 建立有来源的宽泛物理
  先验；不得产生候选方程、单项式列表、系数、次数或 PySR 模板。
- 第一轮闭环检查要求 `plan.md` 含有效的 `EVO_INITIAL_PRIORS` 块。

## 架构

单 Agent + HCC（Hierarchical Cognitive Caching）分层记忆，四阶段闭环迭代。

```
┌─────────────────────────────────────────────────────┐
│                HamiltonPlayground                    │
│       (多轮编排 + 预算/preflight + closure 审计)       │
└─────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────┐
│  RoundExp                 PromotionExp               │
│  Discovery + Verification → Promotion + Finish       │
└─────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────┐
│                  单 Agent 闭环                        │
│  Discovery → Verification → Promotion → Finish       │
│  (变量分析/PySR/拟合) (残差/OOD) (写L2) (signal)      │
└─────────────────────────────────────────────────────┘
```

### 每轮流程

```
Round N 开始
    │
    ├─ 系统: 创建 history/round{N}/trace.md（L1 工作记忆）
    ├─ 系统: 快照 L2 文件 mtime（用于 post-check）
    │
    ├─ RoundExp：同一个 Agent 执行 Discovery + Verification
    │     ├─ 读 L2 → 变量分析 → 拟合/PySR
    │     ├─ 残差、轨迹和可用 OOD 层级验证
    │     └─ 产生 completed result JSON
    ├─ controller：冻结 promotion_input.json（结果路径 + SHA-256）
    ├─ PromotionExp：同一个 Agent 执行 Promotion + Finish
    │     ├─ 不得重新配置或运行 PySR
    │     ├─ 提炼结论到 findings.md + plan.md
    │     └─ 发出 satisfied 信号
    │
    ├─ 系统: 解析 satisfied 信号
    ├─ 系统: closure 与科学治理审计
    │     ├─ 检查 trace、结果 JSON、findings、plan 和 finish
    │     ├─ 检查初始文献先验、incumbent 与 promotion gates
    │     └─ 检查下一轮契约及唯一配置叶字段变更
    │
Round N 结束 → closed=false ? 立即停止 : 按 satisfied 决定结束或下一轮
```

若 completed result 已存在而 Promotion 未闭合，下一次运行直接恢复 `PromotionExp`，不会
重跑 `RoundExp` 或 PySR preflight。两个 Exp 使用同一个 Hamilton Agent，但拥有独立
trajectory 和 token 上限。

### HCC 分层记忆

| 层级 | 文件 | 生命周期 | 内容 |
|------|------|----------|------|
| **L1** | `history/round{N}/trace.md` | 每轮独立 | 当前轮的操作记录、指标、工作笔记 |
| **L2** | `plan.md` | 持久积累（阶梯形） | 战略计划、当前最优、策略队列、失败方法 |
| **L2** | `findings.md` | 持久积累（阶梯形） | 验证结论、实验结果表、最优方程演化 |

L2 文件驱动跨轮知识传递：Agent 每轮读取 L2 → 基于历史做决策 → 将新发现提炼回 L2。

---

## 文件结构

```
playground/hamilton/
├── core/
│   ├── playground.py      # HamiltonPlayground: 多轮编排 + workspace 初始化
│   ├── exp.py             # RoundExp: Discovery + Verification
│   ├── promotion_exp.py   # PromotionExp: 恢复、L2、Finish 与治理审计
│   └── constants.py       # Signal markers、字段定义
├── prompts/
│   ├── hamilton_system.txt          # 当前开发系统提示
│   ├── hamilton_user.txt            # 当前开发用户提示
│   └── hamilton_*_system/user.txt   # 诊断、历史或实验专用提示
├── benchmarks/
│   └── viv/private/       # controller 私有 test/OOD/答案资产（Git ignored）
├── workspace/             # 模板目录（自动 seed 到 run workspace）
│   ├── task.md            # 任务描述（含数据路径和评估标准）
│   └── input/             # 仅公开训练 CSV
├── README.md
├── DEVELOPMENT.md           # 协作开发入口与目录职责
└── TODO.md
```

### Run Workspace（运行时）

```
{run_dir}/workspace/
├── task.md                # 任务描述（只读）
├── plan.md                # L2 战略（当前最优 + 策略队列 + 失败方法）
├── findings.md            # L2 知识（验证结论 + 实验结果 + 最优方程演化）
├── input/                 # 数据文件（只读）
├── lib/                   # 可复用脚本（跨轮持久）
│   └── README.md          # 脚本索引
└── history/
    └── round{N}/
        ├── trace.md       # L1 工作记忆（每轮独立）
        ├── scripts/       # Agent 写的脚本
        └── results/       # 每轮结果 + 派生数据
```

---

## 核心组件

### PySR Skill (`evomaster/skills/pysr/`)
- PySR API 速查和模板指南
- Agent 通过 `use_skill pysr get_info` / `get_reference` 按需加载

### 标准 SR 实验 Skill (`evomaster/skills/run-sr-experiment/`)

- Agent 只创建 JSON 实验配置，不再临时编写 PySR 脚本
- `run_experiment.py` 统一执行数据白名单检查、连续时间验证划分、PySR 搜索、基础指标和短时 ODE 积分
- 对最终选择的原单位方程输出结构化残差诊断：状态依赖、训练分箱、时间相关、
  频谱以及可选的振子半径/相位分箱；不保存逐点残差
- 可选公开 Tier 0 长期动力学验证：冻结稳态窗口、稳健幅值、主频、观测/零/大初值、
  吸引子一致性和结构化积分失败；默认不改变历史 scientific score
- OOD 采用四级协议：Tier 0 连续时间内部验证；Tier 1 同工况不同初态；
  Tier 2 共享方程的留一工况验证；Tier 3 外部工况一次性最终验收
- Tier 1--3 由 workspace 外的控制器对冻结候选执行，并用私有账本限制访问次数；
  Tier 3 验收后写入锁文件，禁止继续自适应搜索
- 强制确定性串行运行，并保存候选方程、数据指纹、环境版本和结构化失败原因
- 先使用 `--validate-only` 检查配置，再执行正式搜索

### Evo Protocol Skill (`evomaster/skills/evo-protocol/`)
- 科学迭代协议（假设 → 实验 → 记录 → 迭代）
- plan 模板（含 Current Best markers）、完整规则、收敛指南

### Signal 机制
- Agent 调用 `finish(message="...", task_completed="true"/"false")` 结束本轮
- 系统从 `task_completed` 判断是否停止迭代（`"true"` = 停止，`"false"` = 继续）
- `finish` 只是闭环证据之一；结果、L2 更新或治理决策缺失时该轮仍为 `closed=false`
- 如果 Agent 未调用 `finish`，当前轮闭环失败，多轮控制器立即停止

### Promotion Exp

- `RoundExp` 只负责产生证据；`PromotionExp` 负责 scientific decision、L2 与 closure。
- `promotion_input.json` 冻结本轮 completed results；恢复前会复核 SHA-256。
- `promotion_state.json` 只记录 `pending/completed`、尝试次数和闭环错误。
- `experiment.promotion.max_tokens` 是 Promotion 单独的 Agent-run 预算；全局预算启用时，
  controller 会在 Discovery 前预留该额度。
- 科学治理启用时，每轮结果必须包含已完成的结构化验证残差诊断；Promotion 必须把与
  result JSON 一致的状态相关和时间相关证据追加为 `EVO_RESIDUAL_FEEDBACK`，并在继续
  研究时将它连同替代解释、预期残差变化和证伪条件写入下一轮契约，否则 closure 失败。
- 标准 runner 在进入 PySR 前将 `search.max_evals` 预扣到
  `.hamilton_evaluation_ledger.json`；失败、拒绝、中断和重放均不返还额度，避免最终
  completed result 主链低估真实物理尝试预算。

---

## 使用方法

```bash
# 准备数据：将 CSV 放入 workspace/input/
cp your_data.csv playground/hamilton/workspace/input/

# 编写任务描述
vim playground/hamilton/workspace/task.md

# 使用权威开发配置运行
python run.py --agent hamilton --config configs/hamilton/config.yaml --task "发现数据中的方程"

# 指定 run 目录
python run.py --agent hamilton --config configs/hamilton/config.yaml `
  --task "task" --run-dir runs/my_experiment
```

### 配置

默认研究入口是 `configs/hamilton/config.yaml`。历史 smoke、恢复和长跑配置的用途与
可复现限制见 `configs/hamilton/README.zh-CN.md`；它们不是可直接复用的正式 benchmark 配置。
协作开发前请阅读 `playground/hamilton/DEVELOPMENT.zh-CN.md`，其中定义了目录职责、提示词唯一
来源、配置生命周期和离线测试命令。

关键配置示例：

```yaml
agent:
  max_turns: 100      # 单轮最大工具调用次数

experiment:
  max_rounds: 10      # 最大迭代轮数
  scientific_governance: true
  require_literature_grounding: true
  promotion:
    max_tokens: 30000
    max_attempts: 2
```

---

## 设计理念

### 外部化记忆（HCC）
不依赖 Agent 内部 memory，用文件作为持久化知识库：
- L1 每轮重置，避免上下文膨胀
- L2 持久积累，确保知识不丢失
- 人类可阅读、检查和干预

### 单 Agent 闭环
一个 Agent 完成发现 → 验证 → 提炼全流程，避免多 Agent 间信息损耗。

### 控制器职责
Agent 负责提出假设和解释证据；控制器负责 workspace 隔离、预算、PySR preflight、标准化
执行、closure 证明、科学治理审计和私有 OOD 访问。控制器验证流程条件，但不替 Agent 生成
科学结论。

### 可调试性
- 每轮脚本保存到 `history/round{N}/scripts/`
- L2 文件记录完整实验演化过程
- L2 post-check 提前发现 Agent 跳过 Promotion 的问题
## 治理式搜索控制

配置 `experiment.search_control` 后，Hamilton 会在 LLM planner 外增加以下确定性控制：

- `search_advancement_gates` 独立更新数值搜索 incumbent，不与最终研究成功所用的更严格
  `scientific_gates` 混用。
- `.hamilton_search_state.json` 保存 incumbent 结果和标准化搜索配置。每个新计划都会相对
  trust-region 基线和 incumbent 锚点检查；达到配置的 stale 轮数后，下一轮基线自动回滚
  到 incumbent 配置。
- `search.max_evals` 归 controller 所有。runner 根据搜索空间大小、近期停滞、累计
  evaluation 账本和后续轮次最低预留量分配实际额度，并在结果和账本中同时记录提议值与
  实际分配值。
- `.hamilton_evidence_memory.json` 是 controller 管理的跨轮证据索引。强证据保存作用域明确、
  已冻结的数值观察和 incumbent 历史；弱证据保存未经检验的因果假设与近失候选。下一轮
  指令只包含紧凑只读视图，而 `findings.md` 继续承担人类可读研究叙事。

没有配置 `experiment.search_control` 的历史 workspace 保持原有行为。
