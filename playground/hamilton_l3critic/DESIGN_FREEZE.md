# Hamilton L3/Critic 设计冻结

## 范围
- 本实现只覆盖 `hamilton_l3critic` playground，不回写现有 `hamilton` playground 的运行协议。
- 共享记忆只服务 Hamilton 类符号回归任务，不尝试抽象为全框架通用层。
- 第一版对抗拓扑固定为 `Hamilton -> Critic -> Hamilton repair -> finish`。

## 冻结决策
- L3 只存可迁移经验卡片，不存完整原始对话或长轨迹。
- L3 卡片首版固定四类：`workflow`、`concept`、`failure_pattern`、`validation_recipe`。
- 共享记忆采用文件型存储，不依赖向量数据库。
- Critic 不是 judge。最终 gate 由结构化规则执行。
- Hamilton 是唯一能对外发出 `task_completed=true/false` 语义的角色。
- Critic 可以用 `finish(task_completed="false")` 结束自身子任务，但其完成信号不参与全局 satisfied 判断。

## 评估口径
- 研究质量：支持集稳定性、跨风速结构一致性、极限环/轨迹行为、OOD 合理性。
- 研究过程：证伪覆盖率、critic 命中历史失败模式的能力、L3 检索命中率。
- 工程代价：轮次数、步骤数、L3 存储增速。

## 明确不做
- 不引入第三个 judge agent。
- 不做全连接 debate 或多 critic 拓扑。
- 不做外部向量数据库与 embedding 依赖。
- 不把 L3 写入时机放在 round 内；首版统一在 task 结束时 promotion。
