# Hamilton L3/Critic

`hamilton_l3critic` 是对原始 `hamilton` playground 的增强版实现：

- 在 HCC 中加入 L3 共享记忆，实现跨任务经验传递
- 引入 `Hamilton -> Critic -> Hamilton repair -> finish` 的稀疏对抗式回合协议
- 保持文件可审计：所有关键状态都落在 task/round 工件中

## 运行方式

```bash
python run.py --agent hamilton_l3critic --task "发现数据中的方程"
```

## 主要差异
- `hamilton`：单 Agent + L1/L2
- `hamilton_l3critic`：双 Agent + L1/L2/L3 + critic gate

## 配置与消融
- `configs/hamilton_l3critic/config.yaml`：完整 L3 + Critic
- `configs/hamilton_l3critic/config_single_agent.yaml`：保留 L3，但关闭 critic
- `configs/hamilton_l3critic/config_l2_only.yaml`：关闭 L3 和 critic
- `configs/hamilton_l3critic/config_shared_retrieval.yaml`：critic 打开，但不做 role-filtered retrieval
