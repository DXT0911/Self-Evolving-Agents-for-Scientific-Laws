#!/usr/bin/env python3
"""NewtonBench Hard 任务批量运行脚本

用 Hamilton agent 跑 NewtonBench hard 难度的所有任务。

使用方式：
  # 跑所有 hard 任务（vanilla_equation，带 PySR）
  python run_newton.py

  # 不用 PySR，纯代码
  python run_newton.py --no-pysr

  # 指定系统类型
  python run_newton.py --system vanilla_equation

  # 指定单个模块
  python run_newton.py --module m0_gravity

  # 指定 law version
  python run_newton.py --module m0_gravity --law-version v0

  # 干跑（只生成任务，不执行）
  python run_newton.py --dry-run
"""

import argparse
import importlib
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# NewtonBench 也需要在 path 中
newton_root = project_root / "NewtonBench"
if str(newton_root) not in sys.path:
    sys.path.insert(0, str(newton_root))

from evomaster.core import get_playground_class

ALL_MODULES = [
    "m0_gravity", "m1_coulomb_force", "m2_magnetic_force",
    "m3_fourier_law", "m4_snell_law", "m5_radioactive_decay",
    "m6_underdamped_harmonic", "m7_malus_law", "m8_sound_speed",
    "m9_hooke_law", "m10_be_distribution", "m11_heat_transfer",
]
SYSTEMS = ["vanilla_equation", "simple_system", "complex_system"]


# ============================================
# Hamilton 框架适配说明（追加到 NewtonBench prompt 后面）
# ============================================
HAMILTON_ADAPTER = """
---

## 实验接口适配

在本框架中，你通过编写 Python 脚本调用实验 API（而非 `<run_experiment>` 标签）。

```python
import sys
sys.path.insert(0, '{newton_root}')
from modules.{module_name}.core import run_experiment_for_module

# 调用实验
result = run_experiment_for_module(
    {example_param}=...,  # 设置参数值
    # ... 其他参数 ...
    noise_level={noise_level},
    difficulty='{difficulty}',
    system='{system}',
    law_version='{law_version}',
)
```

**与原始协议的差异：**
- 你可以在一个脚本中批量调用任意多次实验，没有轮次限制
- 不需要使用 `<run_experiment>` 或 `<final_law>` 标签
- 将发现的方程写入 `findings.md`，通过 `finish` 工具结束
- 充分利用 Python 生态（numpy, scipy, sklearn, sympy）进行数据分析和拟合
"""


def build_task_description(
    module_name: str,
    system: str,
    law_version: str,
    noise_level: float = 0.0,
) -> str:
    """从 NewtonBench 模块导入原始 prompt，追加框架适配说明"""

    # 动态导入模块，获取原始 prompt
    module = importlib.import_module(f"modules.{module_name}")
    newton_prompt = module.get_task_prompt(
        system=system,
        is_code_assisted=True,
        noise_level=noise_level,
    )

    # 获取第一个参数名作为示例
    params = module.PARAM_DESCRIPTION.strip().split("\n")[0]
    # 提取 "- param_name:" 中的 param_name
    example_param = params.split(":")[0].replace("-", "").strip()

    # 追加框架适配
    adapter = HAMILTON_ADAPTER.format(
        newton_root=newton_root,
        module_name=module_name,
        example_param=example_param,
        noise_level=noise_level,
        difficulty="hard",
        system=system,
        law_version=law_version,
    )

    return newton_prompt + adapter


def get_law_versions(module_name: str, difficulty: str = "hard"):
    """获取模块的可用 law version 列表"""
    module = importlib.import_module(f"modules.{module_name}")
    if hasattr(module, "get_available_law_versions"):
        return module.get_available_law_versions(difficulty)
    return ["v0", "v1", "v2"]


def run_newton_tasks(args):
    """主运行逻辑"""
    logger = logging.getLogger(__name__)

    # 确定要跑的模块
    modules = [args.module] if args.module else ALL_MODULES

    # 确定系统类型
    systems = [args.system] if args.system else ["vanilla_equation"]

    # 生成任务列表
    tasks = []
    for module_name in modules:
        for system in systems:
            versions = [args.law_version] if args.law_version else get_law_versions(module_name)

            for version in versions:
                task_id = f"{module_name}__{system}__{version}"
                task_desc = build_task_description(
                    module_name, system, version,
                )
                tasks.append({
                    "id": task_id,
                    "module": module_name,
                    "system": system,
                    "law_version": version,
                    "description": task_desc,
                })

    logger.info(f"Generated {len(tasks)} tasks")
    for t in tasks:
        logger.info(f"  - {t['id']}")

    if args.dry_run:
        print("\n" + "=" * 60)
        print(f"DRY RUN: {len(tasks)} tasks generated")
        print("=" * 60)
        if tasks:
            print(f"\nExample task ({tasks[0]['id']}):\n")
            print(tasks[0]["description"])

        out_path = project_root / "newton_hard_tasks.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(tasks, f, ensure_ascii=False, indent=2)
        print(f"\nTask list saved to {out_path}")
        return

    # 自动导入 playground
    from run import auto_import_playgrounds
    auto_import_playgrounds()

    # 确定配置
    if args.config:
        config_path = Path(args.config)
    elif args.no_pysr:
        config_path = project_root / "configs" / "hamilton" / "config_no_pysr.yaml"
    else:
        config_path = project_root / "configs" / "hamilton" / "config.yaml"

    # 运行目录
    tag = "no_pysr" if args.no_pysr else "pysr"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = project_root / "runs" / f"newton_hard_{tag}_{timestamp}"

    logger.info(f"Config: {config_path}")
    logger.info(f"Run dir: {run_dir}")

    # 串行执行每个任务
    results = []
    for i, task in enumerate(tasks):
        logger.info("=" * 60)
        logger.info(f"[{i+1}/{len(tasks)}] {task['id']}")
        logger.info("=" * 60)

        try:
            playground = get_playground_class("hamilton", config_path=config_path)
            playground.set_run_dir(run_dir, task_id=task["id"])
            result = playground.run(task_description=task["description"])
            result["task_id"] = task["id"]
            results.append(result)
            logger.info(f"  -> {result['status']}")
        except Exception as e:
            logger.error(f"  -> FAILED: {e}", exc_info=True)
            results.append({
                "task_id": task["id"],
                "status": "failed",
                "error": str(e),
            })

    # 汇总
    success = sum(1 for r in results if r.get("status") == "completed")
    logger.info("=" * 60)
    logger.info(f"Done: {success}/{len(results)} completed")
    logger.info(f"Results: {run_dir}")
    logger.info("=" * 60)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    parser = argparse.ArgumentParser(description="Run NewtonBench hard tasks with Hamilton agent")
    parser.add_argument("--module", choices=ALL_MODULES, help="Run single module (default: all)")
    parser.add_argument("--system", choices=SYSTEMS, default="vanilla_equation",
                        help="Experiment system (default: vanilla_equation)")
    parser.add_argument("--law-version", help="Specific law version (e.g. v0, default: all)")
    parser.add_argument("--config", help="Override config path")
    parser.add_argument("--no-pysr", action="store_true", help="Use no-PySR config (pure code)")
    parser.add_argument("--dry-run", action="store_true", help="Generate tasks without running")
    args = parser.parse_args()

    run_newton_tasks(args)


if __name__ == "__main__":
    main()
