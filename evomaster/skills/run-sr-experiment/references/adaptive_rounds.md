# Adaptive rounds

For round N > 1, change one primary factor supported by `config_schema.md`. Keep controls
unchanged and write outputs under `history/roundN/`.

When continuing, maintain this block in `plan.md`:

```text
<!-- EVO_NEXT_ROUND_BEGIN -->
## 下一轮实验契约
- 上轮失败：
- 原因假设：
- 下一轮主变量：
- 保持不变：
- 预期证据：
- 成功标准：
- 失败后的策略：
<!-- EVO_NEXT_ROUND_END -->
```

The primary variable must identify an actual JSON field. State a directional change and
an observable expected effect. Do not count experiment IDs, seeds, or output paths as the
primary adaptation. Use exactly one leaf path; comma-separated fields or multiple changed
configuration leaves invalidate the round.

After execution:

- append verified evidence to `findings.md`;
- record whether the causal hypothesis was supported;
- update the incumbent and scientific decision block defined in `scientific_governance.md`;
- replace the contract with the next one if research remains incomplete;
- call `finish(task_completed="false")` to request another round.
