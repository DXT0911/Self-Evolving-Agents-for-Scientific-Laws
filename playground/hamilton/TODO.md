# Hamilton Agent

## 架构

单 Agent 迭代式方程发现系统，使用 HCC（Hierarchical Cognitive Caching）分层记忆。

```
每轮:
  系统 → 创建 history/round{N}/trace.md（L1 工作记忆）
  RoundExp → 同一 Agent 读 L2 → 发现方程 → 验证 → 产生冻结结果
  PromotionExp → 同一 Agent 提炼到 L2（findings.md + plan.md）→ finish(satisfied)
  系统 → 审计结果、L2、finish、科学决策和下一轮契约，决定是否继续
```

记忆分层：
- **L1 (history/round{N}/trace.md)**：每轮独立的工作记忆
- **L2 (plan.md, findings.md)**：只增不减的知识积累（阶梯形）

## 目录

```
workspace/
├── task.md                    # 任务描述（只读，含数据路径和评估标准）
├── plan.md                    # L2 战略（当前最优 + 策略队列 + 失败方法）
├── findings.md                # L2 知识（验证结论 + 实验结果 + 建议）
├── input/                     # 数据文件（只读）
├── lib/                       # 可复用脚本（跨轮持久）
│   └── README.md              # 脚本索引
├── skills/
│   └── pysr/                  # PySR API 文档（symlink，只读）
└── history/
    └── round{N}/
        ├── trace.md           # L1 工作记忆（每轮独立）
        ├── promotion_input.json # controller 冻结的 Promotion 输入
        ├── promotion_state.json # pending/completed 与恢复尝试
        ├── scripts/           # Agent 写的脚本
        └── results/           # 每轮结果 + 派生数据
```

## 核心组件

### PySR Skill (`evomaster/skills/pysr/`) — 知识层
- SKILL.md: PySR API 速查
- references/: API 参考、模板指南、输出格式
- Agent 通过 `use_skill pysr get_info` / `get_reference` 按需加载

### 标准 SR 实验 Skill (`evomaster/skills/run-sr-experiment/`) — 执行层
- [x] JSON 配置驱动的确定性 PySR runner
- [x] 训练数据白名单与工作区路径边界检查
- [x] 连续时间块内部验证
- [x] 候选、指标、短时 ODE 和复现信息的 JSON 输出
- [x] 配置契约测试与 U248 低预算验收
- [x] 结构化残差诊断、候选重排、标准化搜索与原单位回变换
- [x] 在严格治理下跑通完整 Hamilton Promotion 与 Finish 闭环

### Evo Protocol Skill (`evomaster/skills/evo-protocol/`) — 方法论
- 科学迭代协议（假设→实验→记录→迭代）
- plan 模板（含当前最优 markers）、完整规则、收敛指南

### Constants (`playground/hamilton/core/constants.py`)
- EUREKA_SIGNAL_BEGIN/END
- CURRENT_BEST_BEGIN/END, STRATEGY_QUEUE_BEGIN/END

## 已完成

- [x] HCC 重构：Agent 自主化 + 分层记忆
- [x] 删除 run_pysr 工具和 experiment.json
- [x] 系统简化：只保留 L1 重置 + satisfied 信号解析
- [x] VIV 多风速基准（5 风速 × 2 组 + 3 bonus OOD）
- [x] task.md 机制（任务描述从 prompt 分离到文件）
- [x] 移除复用工具库（eurekatool + workspace/tools/）
- [x] evo-protocol 中文化
- [x] 双 Agent → 单 Agent 重构：合并 Hamilton + Eureka 为单 Agent，每轮完成发现→验证→提炼闭环
  - config.yaml: `agents:` → `agent:` 单 agent 模式
  - exp.py: 去掉 eureka_agent，单次 agent.run()
  - playground.py: 使用 BasePlayground 的 self.agent
  - 删除 eureka_system.txt / eureka_user.txt
  - hamilton_system.txt: 合并四阶段（Discovery → Verification → Promotion → Finish）
- [x] 修复双→单 Agent 重构残留（"Eureka 维护"文本、过时常量字段）
- [x] 添加 L2 post-check（检测 Agent 是否完成 Promotion，warning 级别）
- [x] 将 L2 post-check 升级为严格 closure 与科学治理审计
- [x] 文献先验合约与 benchmark 答案隔离
- [x] Tier 0--3 OOD 冻结、私有账本和最终锁协议
- [x] token/evaluation 预算与 Julia/PySR controller preflight
- [x] Promotion 从 RoundExp 拆为 EvoMaster 原生 `PromotionExp(BaseExp)` 阶段
- [x] Promotion 结果冻结、SHA-256 恢复检查、独立 token 预算和尝试上限
- [x] runner、phase orchestration、closure、governance、安全、OOD 和 preflight 合约测试
- [x] README.md 重写（单 Agent + HCC 架构）
- [x] L1 trace.md 移入 round 目录（不再覆写根目录 execution_trace.md）

## TODO

### HCC 混合线路：slim 治理修复 + 正式实验（2026-08-17 起）

- [x] 修复：`governance_mode: slim` 未触发 `initialize_control`（旧代码只看
  `scientific_governance` 布尔），导致无 `.hamilton_search_control.json` →
  runner 的 `allocate_dynamic_evaluations` 不生效 → Round 1 自由选 `max_evals=4500`
  吞掉整个预算，Round 2 被累计预算门 `consumed=4500+requested>limit` 阻断。
  修复：`playground.py` `_init_workspace` 用 `_search_control_active`
  （full/slim/legacy 布尔）替代旧判断，`promotion_exp._governance_mode` 语义保持一致。
- [x] 实测 Round 1 成本：discovery 526,536 + promotion 57,906 = 584,442 token；
  incumbent score 0.676（static_s02，真实方程 + 残差推理，可读记忆质量好）。
- [x] 复跑 smoke 验证（2026-08-18，exit 0，3 轮全 closed，`experiment_20260818_001612.json`）：
  - 预算正确分配 1500×3=4500，累计账本无阻断；round2/3 单字段变更 gate 正常
    （R2 加 unary=square，R3 改 complexity weight 0.05→0.01）；warm-start + trust-region state 持久化正常。
  - 真实成本（deepseek-v4-flash，static_s02）：R1=219,604 / R2=637,269 / R3=659,826，
    合计 **1,516,699 token**（≈506k/轮；R2/R3 因 L2 记忆 + 残差反馈 JSON 增长而翻倍）。
  - ✅ 科学信号（已纠正方向误读）：`scientific_score` 是**越小越好**（`hamilton_system.txt`
    "Minimize scientific score"；v6 `score < incumbent` → promote；`collect` `left < right` → win）。
    val R² 单调上升 0.523→0.585→0.601，scientific_score 单调下降 0.7084→0.6682→0.6418，
    二者**同向单调改进**（score 越低 = loss 越小 = 越好），不存在背离。pilot 主判据方向即
    "最终 incumbent scientific_score 越小越优，H < B 判 H 胜"。
  - 每轮改一个字段（先验/operator/复杂度权重）确实改变了下轮搜索，闭环可靠，可读记忆质量高。
- [x] 3 seed × 2 task pilot（v4-flash，冻结 manifest + 配对 seed + engine evals），
  2026-08-18 跑完 12/12 cells（B 臂 6/6 rc=0 + H 臂 6/6，H 臂 5 个 rc=0 + 1 个 rc=1）。
  - **主判据（配对符号检验，scientific_score 越小越优）**：H 胜 2 / 负 0 / 平 4，n=2，
    p_two_sided=0.5（不显著；开发性 pilot，n 太小，结论为"从不劣于 B，无统计显著信号"）。
    - static_s02：r1 平(0.02419)、r2 平(0.02508)、r3 **H 胜**(0.29924 vs 0.35061)。
    - dynamic_d01：r1 平(0.73408)、r2 平(0.82218，stale，见下)、r3 **H 胜**(0.60685 vs 0.75157)。
  - **发现（已按"接受现状"记录）**：`experiment.promotion.max_tokens: 400000` 对 dynamic_d01
    偏低。dynamic_d01/repeat_2 第 3 轮 promotion 阶段 LLM 已耗 254,729 token、下一次调用需
    再 ~148k → 超 400k → `Token budget preflight stopped run` 截断，finish 未调用 → round-3
    晋升（0.54047，已产生并验证于 `history/round3/results/result.json`，promotion 裁决确认
    `promote`）未写回 `.hamilton_search_state.json`，incumbent 停留在 round-1 的 0.82218。
    - 若计入 round-3 真实分数，该 cell 应为 H 胜（0.54047 < 0.82218），sign test 变
      3 胜 0 负 3 平（n=3，p=0.25），仍不显著。
    - 处理：主判据采纳 stale 值（平局）；token 预算失败作为 pilot finding 记录，不在本 pilot 重跑。
    - 复现者注意：H 臂单 run 实测 1.01M–1.90M token（与 smoke 的 ~1.5M 一致），manifest 软上限
      3M 正确，但 `promotion.max_tokens` 是 promotion 阶段的**硬**上限，dynamic 类任务建议 ≥1M。

### Hamilton v6：LLM 因果消融（2026-08-16 起）

设计文档：`../../docs/sragent/HAMILTON_V6_CAUSAL_ABLATION_DESIGN_2026-08-16.zh-CN.md`
运行清单：`../../docs/sragent/HAMILTON_V6_RUN_CHECKLIST_2026-08-17.zh-CN.md`

- [x] 打通 LLM 因果路径：原子动作白名单（continue_warm / adjust_parsimony /
  add_operator / remove_operator / restart_same）
- [x] `governed_policy.py`：`normalize_atomic_action` + `choose_atomic_action`（arm B 规则）
- [x] `compressed_planner.py`：`call_atomic_planner`（arm C 原子动作 planner）
- [x] `search_control.py`：`review_planner_proposal`（采纳/拒绝 + 规则回退）+ `persist_binding_action`
- [x] runner + warm worker 支持 restart 轮（`round_action=restart` → `model=None` 重建 + 算子字段兼容）
- [x] 契约测试 `test_atomic_policy.py`（15 用例，离线）
- [x] 新建 `experiments/hamilton_vs_pysr_governed_search_v6/`（manifest/build/execute/collect）
- [x] `configs/hamilton/config_governed_pysr_v6_pilot.yaml`
- [x] 冻结值：3 臂 A/B/C × static_s02 + dynamic_d01 × seeds 8401–8403，每 arm/seed 4500 evals
- [ ] 请求用户授权实际运行（需 `HAMILTON_API_KEY` + PySR/Julia）
- [ ] 运行后 collect + 归因（C−A、C−B、B−A、engine evals 对齐）

关键约束：warm worker 跨轮只允许改 `search.parsimony`；算子变更等价于冷重启（丢种群）。
这是 v6 的核心权衡——v1 唯一的正信号（加 tanh）正是算子变更，而 A/B/C 三臂同等承担
重启成本，归因时按 engine-measured evals 对齐。

### Hamilton v4：确定性治理优化（2026-08-14）

- [x] 收缩 LLM 权限为受限结构假设；controller 负责动作、候选保留、回滚和预算
- [x] 增加 additive term leave-one-out 重拟合信用诊断
- [x] 将 L2 controller memory 分为 elite、motifs、failures、diagnostics 并按状态路由
- [x] 增加不调用 PySR/LLM 的冻结结果 decision replay
- [x] 在 v3 三轮结果上完成 replay；冻结 policy 三轮均建议 `continue`
- [x] 修复 Promotion 过早退出：已通过审计的 artifacts 由 controller 确定性 finish，
  不再进入第二次 LLM token preflight
- [ ] 冻结 v4 binding policy、三 paired seeds、四臂预算后再请求用户授权新实验

完整任务和证据见
`../../docs/sragent/HAMILTON_V4_OPTIMIZATION_TASKS_2026-08-14.zh-CN.md`。

- [x] **P0：将 Promotion 做成确定性、可恢复且有独立预算的阶段（合约实现）**
- [x] P0：用真实对话验收 PromotionExp 的冻结、恢复和 Finish 闭环
- [x] P0：严格治理下完成一次不使用私有 test/OOD 的多轮闭环验收
- [x] P0：完成 R4--R8 受控长跑；五轮均 `closed=true`，R5 incumbent 保持到终轮
- [x] P0：修复终轮错误要求 `EVO_NEXT_ROUND` 的 continuation contract 缺陷
- [x] P0：将结构化残差恢复为 Verification → Promotion → 下一轮契约的强制反馈通道
- [x] P0：按物理尝试预扣并累计 accepted/rejected/failed/replayed PySR evaluation 预算
- [x] P1：预注册 governed Hamilton、ordinary PySR 与 matched-restart PySR 的公开数据
  对照实验；准备态清单禁止调用 LLM、PySR/Julia 和 private/OOD
- [x] P1：完成三个公开任务、每个任务一个重复的 9-arm 运行门；结果为混合正信号，
  不是正式多重复 benchmark 结论
- [x] P1：扩展公开 Tier 0 长期 VIV 动力学验证器（稳态振幅、频率、零/大初值、
  吸引子一致性、结构化稳定性失败和可选 scientific-score penalty）
- [x] P1：用合成稳定平衡、极限环、发散、漂移、周期不足和非均匀网格校准长期验证器，
  并对公开 U248 运行门的七个历史候选完成事后敏感性回放
- [ ] P1：冻结 direct PySR、fit-only Hamilton、dynamics-aware Hamilton 的可比配置
- [ ] P1：用正式私有 manifest 按 Tier 1 → Tier 2 → Tier 3 完成受控验收
- [x] P2：增加 controller-only ground truth 注册表、代数/挑战网格等价验证和
  不向 Agent 泄露答案的公开静态/动力学任务基础设施
- [x] P2：发布 v1 运行门的字段白名单公开证据包、固定 revision 数据获取脚本和协作者
  Codex 交接文档
- [x] P2：冻结排除 VIV 的 Hamilton-vs-PySR v2 开发/验证/测试任务划分、四实验臂、
  四类指标和最大资源预算
- [ ] P2：为 v2 增加引擎实测 evaluation 遥测、union-schedule 基线、执行配置一致性审计
  和完整 launch-bundle 测试
- [ ] P2：完成 v2 运行门、验证集策略选择和五重复封存测试

R1--R8 受控实验已完成。当前 incumbent 为 `1.1619 - 1.8606x³`，scientific score 为
`0.954`，但速度依赖、验证 R² 和 scientific score 成功门槛均未通过。该结果证明严格多轮闭环
可以运行，并表明当前搜索设置未找到稳定的速度项；不能据此声称 Hamilton 已完成通用科学
定律发现，也不能把“未发现速度项”解释为真实物理定律中必然不存在速度项。
