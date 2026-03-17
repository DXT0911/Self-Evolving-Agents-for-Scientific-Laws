<!-- SRBENCH_ANCHOR_FULL_PACK_POLICY -->

# Full Problem Packs

这个目录存放带 `test` / `OOD` 数组的完整 OpenEvolve problem pack。

用途：
- 给 `post_eval_candidate.py` / `compare_methods.py` 做正式 shared post-eval
- 保持与 `playground/hamilton_srbench/problems/` 分离，避免 Hamilton 在搜索阶段看到 held-out 数据

约束：
- Hamilton 搜索阶段只应读取 `playground/hamilton_srbench/problems/`
- 正式对比阶段才读取这里的 full pack
- 如果重新导出 problem 且带 `--include-hidden`，默认应落到这个目录
