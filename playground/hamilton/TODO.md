# Hamilton Agent

## 架构

单 Agent 迭代式方程发现系统，使用 HCC（Hierarchical Cognitive Caching）分层记忆。

```
每轮:
  系统 → 创建 history/round{N}/trace.md（L1 工作记忆）
  Agent → 读 L2 → 发现方程 → 验证 → 提炼到 L2（findings.md + plan.md）→ finish(satisfied)
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
- [ ] 在严格治理下跑通完整 Hamilton Promotion 与 Finish 闭环

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
- [x] 44 项 runner、closure、governance、安全、OOD 和 preflight 合约测试
- [x] README.md 重写（单 Agent + HCC 架构）
- [x] L1 trace.md 移入 round 目录（不再覆写根目录 execution_trace.md）

## TODO

- [ ] **P0：将 Promotion 做成确定性、可恢复且有独立预算的阶段**
- [ ] P0：严格治理下完成一次不使用私有 test/OOD 的多轮闭环验收
- [ ] P1：扩展长期 VIV 动力学验证器（稳态振幅、频率、零/大初值和吸引子一致性）
- [ ] P1：冻结 direct PySR、fit-only Hamilton、dynamics-aware Hamilton 的可比配置
- [ ] P1：用正式私有 manifest 按 Tier 1 → Tier 2 → Tier 3 完成受控验收
- [ ] P2：增加已知 ground truth 且无答案泄露的合成方程 benchmark

正式实验当前暂停。历史 smoke 和旧多轮结果仅用于流水线验收与失败诊断，不能作为 Hamilton
已经完成通用科学定律发现的证据。
