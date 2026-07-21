"""Hamilton Playground 实现

符号回归Agent - 过完备变量下的方程发现

模式：
- RoundExp: 单轮执行单元（单 Agent 完成发现→验证→提炼闭环）
- Playground: 循环编排，多次调用RoundExp

HCC 分层记忆：
- L1 (history/round{N}/trace.md): 每轮独立的工作记忆
- L2 (plan.md, findings.md): 只增不减的知识积累
"""

import json
import logging
import shutil
import sys
from pathlib import Path
from datetime import datetime

# 确保可以导入evomaster模块
_module_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_module_root) not in sys.path:
    sys.path.insert(0, str(_module_root))

from evomaster.core import BasePlayground, register_playground
from .constants import CURRENT_BEST_BEGIN, CURRENT_BEST_END, STRATEGY_QUEUE_BEGIN, STRATEGY_QUEUE_END

from .exp import RoundExp
from .pysr_preflight import PySRPreflightError, run_preflight


@register_playground("hamilton")
class HamiltonPlayground(BasePlayground):
    """Hamilton Playground - 符号回归Agent

    编排多轮迭代：
    1. 创建单个 Agent（发现 + 验证 + 提炼）
    2. 循环调用 RoundExp (每轮)
    3. 记录实验结果

    每轮流程（HCC）：
    - 系统: L1 trace.md 在每轮 round 目录创建
    - Agent: 读 L2 → 发现方程 → 验证 → 提炼到 L2 → finish(satisfied)
    - 系统: 解析 signal，决定继续/停止

    使用方式：
        python run.py --agent hamilton --task "发现数据中的方程"
    """

    def __init__(self, config_dir: Path = None, config_path: Path = None):
        """初始化 Hamilton Playground"""
        self._project_root = Path(__file__).resolve().parent.parent.parent.parent

        if config_path is None and config_dir is None:
            config_dir = self._project_root / "configs" / "hamilton"

        super().__init__(config_dir=config_dir, config_path=config_path)
        self.logger = logging.getLogger(self.__class__.__name__)

        # Agents
        self.workspace_dir: Path | None = None

        # 实验记录
        self.experiment_record = {
            "task": "",
            "rounds": [],
            "start_time": datetime.now().isoformat(),
        }

    def set_run_dir(self, run_dir: str | Path, task_id: str | None = None) -> None:
        """设置 run 目录。

        Workspace seeding and file initialization are deferred to _init_workspace()
        which is called at run() time when the task description is available.
        """
        super().set_run_dir(run_dir, task_id=task_id)

    def _init_workspace(self) -> None:
        """Initialize workspace with L2 persistent files.

        Seeds task.md and input/ from the Hamilton workspace template, then creates
        findings.md, plan.md and lib/ if they do not exist.
        """
        workspace = self.workspace_dir
        if not workspace:
            return

        workspace.mkdir(parents=True, exist_ok=True)

        experiment_cfg = getattr(self.config, "experiment", {})
        if isinstance(experiment_cfg, dict) and experiment_cfg.get("max_total_evals"):
            (workspace / ".hamilton_budget.json").write_text(
                json.dumps(
                    {"max_total_evals": int(experiment_cfg["max_total_evals"])},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

        template_workspace = self._project_root / "playground" / "hamilton" / "workspace"
        template_task = template_workspace / "task.md"
        workspace_task = workspace / "task.md"
        if template_task.exists() and not workspace_task.exists():
            shutil.copy2(template_task, workspace_task)
            self.logger.info(f"Seeded {workspace_task}")

        template_input = template_workspace / "input"
        workspace_input = workspace / "input"
        if template_input.exists() and not workspace_input.exists():
            shutil.copytree(template_input, workspace_input)
            self.logger.info(f"Seeded {workspace_input}")

        # findings.md (L2 — knowledge accumulation, append-only)
        findings_file = workspace / "findings.md"
        if not findings_file.exists():
            findings_file.write_text(
                "# 研究发现\n\n"
                "## 关键洞察\n"
                "（经验证的数据观察和物理关系）\n\n"
                "## 实验结果\n"
                "| 轮次 | 方法 | 方程 | MSE (训练) | MSE (OOD) | 结论 |\n"
                "|------|------|------|-----------|-----------|------|\n\n"
                "## 最优方程演化\n"
                "（记录最优方程在各轮中的变化过程）\n",
                encoding="utf-8",
            )
            self.logger.info(f"Created {findings_file}")

        # lib/ (L2 — reusable scripts, persists across rounds)
        lib_dir = workspace / "lib"
        lib_dir.mkdir(parents=True, exist_ok=True)
        lib_readme = lib_dir / "README.md"
        if not lib_readme.exists():
            lib_readme.write_text("# lib/ 可复用脚本索引\n\n（每次新增脚本时更新）\n", encoding="utf-8")

        # plan.md (L2 — strategic plan with Current Best markers)
        plan_file = workspace / "plan.md"
        if not plan_file.exists():
            self._create_plan_file(plan_file)
            self.logger.info(f"Created {plan_file}")

    def setup(self) -> None:
        """初始化组件（复用 BasePlayground.setup）"""
        self.logger.info("Setting up Hamilton playground...")
        super().setup()

        if self.session is not None:
            try:
                self.workspace_dir = Path(self.session.config.workspace_path)
            except Exception:
                self.workspace_dir = None

        if self.agent is None:
            raise ValueError("Hamilton requires 'agents.hamilton' section in config.yaml")

        self.logger.info("Hamilton playground setup complete")

    def run(self, task_description: str, output_file: str | None = None) -> dict:
        """运行多轮实验

        Args:
            task_description: 任务描述
            output_file: 结果保存文件

        Returns:
            运行结果
        """
        try:
            self.setup()

            # 设置轨迹文件
            self._setup_trajectory_file(output_file)

            # 更新实验记录
            self.experiment_record["task"] = task_description

            # 获取最大轮数
            experiment_cfg = getattr(self.config, 'experiment', {})
            if not isinstance(experiment_cfg, dict):
                experiment_cfg = {}
            max_rounds = int(experiment_cfg.get('max_rounds', 5) or 5)
            start_round = int(experiment_cfg.get("start_round", 1) or 1)
            max_total_tokens = int(experiment_cfg.get("max_total_tokens", 0) or 0)
            per_round_tokens = int(experiment_cfg.get("max_tokens_per_round", 0) or 0)
            stall_rounds = int(experiment_cfg.get("stall_rounds", 0) or 0)
            total_tokens = 0
            stale_count = 0
            incumbent_score = None
            termination_reason = "max_rounds_reached"

            self.logger.info(f"Starting Hamilton experiment with {max_rounds} max rounds")
            self.logger.info(f"Task: {task_description}")

            # 初始化workspace
            self._init_workspace()
            preflight_cfg = experiment_cfg.get("pysr_preflight", {})
            if not isinstance(preflight_cfg, dict):
                raise ValueError("experiment.pysr_preflight must be a mapping")
            if preflight_cfg.get("enabled", True):
                preflight_timeout = int(
                    preflight_cfg.get("timeout_seconds", 180) or 180
                )
                self.logger.info(
                    "Running Julia/PySR preflight before the first agent round"
                )
                try:
                    preflight_result = run_preflight(
                        timeout_seconds=preflight_timeout
                    )
                except PySRPreflightError as exc:
                    raise RuntimeError(
                        "Julia/PySR preflight failed before any LLM or search "
                        f"budget was consumed: {exc}"
                    ) from exc
                self.experiment_record["pysr_preflight"] = preflight_result
                self.logger.info(
                    "Julia/PySR preflight ready: PySR %s, Julia %s, %.3fs",
                    preflight_result["warmup"]["pysr_version"],
                    preflight_result["warmup"]["julia_version"],
                    preflight_result["warmup"]["controller_elapsed_seconds"],
                )
            final_ood_lock = (
                self.workspace_dir / ".hamilton_final_ood.lock"
                if self.workspace_dir
                else None
            )
            if final_ood_lock and final_ood_lock.is_file():
                raise RuntimeError(
                    "This workspace has a finalized tier3 OOD attestation; "
                    "further adaptive rounds are prohibited."
                )

            # 循环执行多轮
            for round_num in range(start_round, max_rounds + 1):
                self.logger.info("=" * 60)

                if max_total_tokens:
                    remaining = max_total_tokens - total_tokens
                    if remaining <= 0:
                        termination_reason = "token_budget_reached"
                        break
                    self.agent.config.max_total_tokens = (
                        min(per_round_tokens, remaining) if per_round_tokens else remaining
                    )
                self.logger.info(f"Round {round_num}/{max_rounds}")
                self.logger.info("=" * 60)

                # 创建单轮exp
                exp = RoundExp(
                    agent=self.agent,
                    config=self.config,
                    round_num=round_num,
                )
                if self.workspace_dir:
                    exp.set_run_dir(self.workspace_dir)

                # 执行单轮
                result = exp.run(task_description)
                signal = result.get("signal") or {}
                round_tokens = self._trajectory_token_usage(result.get("trajectory"))
                total_tokens += round_tokens

                # 记录结果（确保可 JSON 序列化；完整轨迹已由 trajectories/trajectory.json 持久化）
                round_record = {
                    "round": result.get("round", round_num),
                    "agent_result": result.get("agent_result", ""),
                    "findings": result.get("findings", ""),
                    "signal": signal,
                    "trajectory": self._summarize_trajectory(result.get("trajectory")),
                    "token_usage": round_tokens,
                }
                self.experiment_record["rounds"].append(round_record)
                self.experiment_record["total_token_usage"] = total_tokens

                if not signal.get("closed", False):
                    self.logger.warning("Stopping because the current round did not close cleanly")
                    termination_reason = "round_incomplete"
                    break

                decision = signal.get("closure", {}).get("scientific_decision", {})
                expected = decision.get("incumbent_expected") or {}
                score = expected.get("score")
                if isinstance(score, (int, float)):
                    if incumbent_score is None or score < incumbent_score - 1e-12:
                        incumbent_score = float(score)
                        stale_count = 0
                    else:
                        stale_count += 1

                # 检查是否完成
                if self._is_satisfied(signal):
                    self.logger.info("Found satisfactory result!")
                    termination_reason = "scientific_success"
                    break
                if max_total_tokens and total_tokens >= max_total_tokens:
                    termination_reason = "token_budget_reached"
                    break
                if stall_rounds and stale_count >= stall_rounds:
                    self.logger.info(f"Stopping after {stale_count} rounds without incumbent improvement")
                    termination_reason = "incumbent_stalled"
                    break

            # 保存实验记录
            self._save_experiment_record()

            final_signal = (
                self.experiment_record["rounds"][-1].get("signal", {})
                if self.experiment_record["rounds"]
                else {}
            )
            return {
                "status": "completed" if final_signal.get("closed") else "incomplete",
                "total_rounds": len(self.experiment_record["rounds"]),
                "research_satisfied": bool(final_signal.get("satisfied", False)),
                "termination_reason": termination_reason,
                "total_token_usage": total_tokens,
                "experiment_record": self.experiment_record,
            }

        except Exception as e:
            self.logger.error(f"Hamilton experiment failed: {e}", exc_info=True)
            return {
                "status": "failed",
                "error": str(e),
            }

        finally:
            self.cleanup()

    def _create_plan_file(self, plan_file: Path):
        """创建 plan.md 研究计划文件"""
        plan_content = f"""# 研究计划

<!-- EVO_INITIAL_PRIORS_BEGIN -->
{{"status": "pending"}}
<!-- EVO_INITIAL_PRIORS_END -->

{CURRENT_BEST_BEGIN}
## 当前最优
- 轮次：0
- 方程：无
- MSE：未知
- 更新时间：{datetime.now().isoformat()}
{CURRENT_BEST_END}

## 数据概览
（首轮 EDA 后填写：变量列表、基本统计、初步观察）

## 当前假设
1. 待定

## 已确认知识
- 相关变量：待定
- 排除变量：待定
- 已发现的关键关系：无

## 策略队列
{STRATEGY_QUEUE_BEGIN}
（Agent 自行制定）
{STRATEGY_QUEUE_END}

## 失败方法
| 轮次 | 策略 | 变量 | 模板/参数 | MSE | 失败原因 |
|------|------|------|-----------|-----|----------|
"""
        plan_file.write_text(plan_content, encoding="utf-8")

    def _summarize_trajectory(self, trajectory) -> dict:
        """提取轨迹的轻量摘要（避免 experiment_record 保存巨大对象）。"""
        try:
            if trajectory is None:
                return {}
            status = getattr(trajectory, "status", None)
            steps = getattr(trajectory, "steps", None)
            steps_n = len(steps) if isinstance(steps, list) else None
            return {"status": status, "steps": steps_n}
        except Exception:
            return {}

    @staticmethod
    def _trajectory_token_usage(trajectory) -> int:
        total = 0
        for step in getattr(trajectory, "steps", []) or []:
            message = getattr(step, "assistant_message", None)
            usage = getattr(message, "meta", {}).get("usage", {}) if message else {}
            total += int(usage.get("total_tokens", 0) or 0)
        return total

    def _is_satisfied(self, signal) -> bool:
        """判断是否找到满意结果（只接受结构化信号，避免关键字误触发）"""
        try:
            if isinstance(signal, dict):
                return bool(signal.get("satisfied", False))
        except Exception:
            pass
        return False

    def _save_experiment_record(self):
        """保存实验记录到 run_dir"""
        try:
            if self.run_dir:
                record_dir = Path(self.run_dir) / "records"
            else:
                record_dir = Path("./runs") / "hamilton" / "records"
            record_dir.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            record_file = record_dir / f"experiment_{timestamp}.json"

            self.experiment_record["end_time"] = datetime.now().isoformat()

            with open(record_file, 'w', encoding='utf-8') as f:
                json.dump(self.experiment_record, f, ensure_ascii=False, indent=2)

            self.logger.info(f"Experiment record saved to {record_file}")

        except Exception as e:
            self.logger.error(f"Failed to save experiment record: {e}")
