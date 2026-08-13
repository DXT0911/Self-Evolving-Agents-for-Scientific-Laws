"""Hamilton Promotion Exp - 科学晋升与闭环审计

负责对已经冻结的实验结果执行 Promotion 与 Finish。

该 Exp 不运行符号回归，只读取 controller 冻结的结果摘要，复用同一个 Hamilton Agent
更新 L2，并对 scientific decision 和 finish 执行确定性审计。

文件规范：
- history/round{N}/trace.md: L1 工作记忆，每轮独立
- findings.md: L2 知识积累，Agent 追加
- plan.md: L2 战略计划，Agent 全权维护（含 Current Best）
"""

import hashlib
import json
import logging
import math
import re
from pathlib import Path

from evomaster.core.exp import BaseExp
from evomaster.agent import BaseAgent
from evomaster.utils.types import TaskInstance
from .search_control import (
    meaningful_config as project_meaningful_config,
    read_control,
    read_state,
)


NEXT_ROUND_BEGIN = "<!-- EVO_NEXT_ROUND_BEGIN -->"
NEXT_ROUND_END = "<!-- EVO_NEXT_ROUND_END -->"
NEXT_ROUND_FIELDS = (
    "上轮失败",
    "原因假设",
    "残差证据",
    "替代解释",
    "下一轮主变量",
    "保持不变",
    "预期证据",
    "预期残差变化",
    "成功标准",
    "证伪条件",
    "失败后的策略",
)
SCIENTIFIC_DECISION_BEGIN = "<!-- EVO_SCIENTIFIC_DECISION_BEGIN -->"
SCIENTIFIC_DECISION_END = "<!-- EVO_SCIENTIFIC_DECISION_END -->"
RESIDUAL_FEEDBACK_BEGIN = "<!-- EVO_RESIDUAL_FEEDBACK_BEGIN -->"
RESIDUAL_FEEDBACK_END = "<!-- EVO_RESIDUAL_FEEDBACK_END -->"
INITIAL_PRIORS_BEGIN = "<!-- EVO_INITIAL_PRIORS_BEGIN -->"
INITIAL_PRIORS_END = "<!-- EVO_INITIAL_PRIORS_END -->"
ALLOWED_CLAIM_STRENGTHS = {"observation", "hypothesis", "supported", "confirmed"}
ALLOWED_SCALE_METHODS = {
    "standardized_feature_effect",
    "term_contribution",
    "dimensional_analysis",
    "not_applicable",
}


class PromotionExp(BaseExp):
    """单轮 Promotion 实验

    负责：
    1. 冻结或恢复本轮 completed result 输入；
    2. 复用 Hamilton Agent 完成 Promotion 与 Finish；
    3. 审计 L2、scientific decision 和下一轮契约。
    """

    def __init__(self, agent, config, round_num, result_files=None, max_attempts=2):
        super().__init__(agent, config)
        self.round_num = round_num
        self.result_files = list(result_files or [])
        self.max_attempts = int(max_attempts)
        self.logger = logging.getLogger(self.__class__.__name__)

    @property
    def exp_name(self) -> str:
        return f"Promotion_{self.round_num}"

    def run(self, task_description: str, task_id: str = "exp_001") -> dict:
        """执行或恢复本轮 Promotion。"""
        self.logger.info(f"Starting Promotion for Round {self.round_num}")

        BaseAgent.set_exp_info(exp_name=self.exp_name, exp_index=self.round_num)

        self._ensure_round_dirs()
        promotion_input = self._load_or_create_promotion_input()
        promotion_evidence = self._write_promotion_evidence(promotion_input)
        state = self._load_promotion_state()
        state_input_sha256 = state.get("input_sha256")
        current_input_sha256 = self._file_digest(self._promotion_input_path())
        if state_input_sha256 and state_input_sha256 != current_input_sha256:
            raise RuntimeError("Promotion state does not match the frozen input")
        if state.get("status") == "completed":
            return state.get("result", {})
        attempts = int(state.get("attempts", 0) or 0)
        if attempts >= self.max_attempts:
            return {
                "round": self.round_num,
                "signal": {
                    "round": self.round_num,
                    "satisfied": False,
                    "closed": False,
                    "promotion_attempts_exhausted": True,
                },
                "trajectory": None,
                "agent_result": "",
                "findings": self._read_findings(),
            }
        self._write_promotion_state({
            "status": "pending",
            "attempts": attempts + 1,
            "input_sha256": self._file_digest(self._promotion_input_path()),
        })

        # 记录 L2 文件状态（用于 post-check）
        l2_snapshot = self._snapshot_l2()
        closure_snapshot = self._snapshot_closure_artifacts()

        self.logger.info(f"[Round {self.round_num}] Running Promotion Agent phase...")
        prior_closure_errors = [
            str(error).strip()
            for error in state.get("errors", [])
            if str(error).strip()
        ]
        recovery_feedback = self._recovery_feedback(
            attempts=attempts,
            prior_closure_errors=prior_closure_errors,
        )
        # A missing error list is not proof that an audit ran: an interrupted LLM
        # request leaves a pending state with no errors. Only a completed closure
        # audit may explicitly authorize the bounded fast-finish path.
        fast_finish_recovery = attempts >= 1 and (
            state.get("fast_finish_eligible") is True
            or self._existing_artifacts_fast_finish_eligible(
                [item["path"] for item in promotion_input["results"]]
            )
        )
        if fast_finish_recovery:
            recovery_feedback += self._fast_finish_feedback(
                round_num=self.round_num,
                attempt_num=attempts + 1,
            )
        task = TaskInstance(
            task_id=f"{task_id}_round{self.round_num}_promotion",
            task_type="hamilton_promotion",
            description=(
                f"{task_description}\n\n"
                "Execute Promotion and Finish only. Do not run or configure PySR. "
                "Use the compact controller-generated promotion_evidence named in "
                "input_data; do not read task.md or the full result JSON unless the "
                "packet explicitly reports missing evidence. In the first response, "
                "read promotion_evidence, trace.md, findings.md, and plan.md in parallel "
                "and load scientific_governance.md once. In the next response, issue "
                "all three file edits in parallel. Then call finish. On a recovery "
                "attempt, make "
                "an explicit current-round recovery edit to all three files even when an "
                "earlier partial attempt already wrote valid content; unchanged files fail "
                "the closure audit."
                f"{recovery_feedback}"
            ),
            input_data={
                "round": self.round_num,
                "promotion_input": str(
                    self._promotion_input_path().relative_to(self.run_dir)
                ).replace("\\", "/"),
                "promotion_evidence": str(
                    self._promotion_evidence_path().relative_to(self.run_dir)
                ).replace("\\", "/"),
                "promotion_evidence_sha256": self._file_digest(
                    self._promotion_evidence_path()
                ),
                "promotion_attempt": attempts + 1,
                "prior_closure_errors": prior_closure_errors,
                "fast_finish_recovery": fast_finish_recovery,
            },
        )
        trajectory = self.agent.run(task)
        agent_result = self._extract_agent_response(trajectory)
        self.logger.info(f"[Round {self.round_num}] Promotion Agent phase completed")

        # 解析 satisfied 信号（系统唯一职责：决定是否继续迭代）
        signal = self._parse_signal(agent_result, trajectory)

        self._check_l2_promotion(l2_snapshot)
        closure = self._check_round_closure(
            closure_snapshot,
            trajectory,
            completed_results=[item["path"] for item in promotion_input["results"]],
        )
        signal["closed"] = closure["closed"]
        signal["closure"] = closure
        if signal.get("satisfied") and not closure["scientific_decision"]["valid"]:
            signal["satisfied"] = False
            signal["governance_rejected_success"] = True

        findings_content = self._read_findings()

        self.logger.info(f"Promotion for Round {self.round_num} completed")

        result = {
            "round": self.round_num,
            "agent_result": agent_result,
            "signal": signal,
            "findings": findings_content,
            "trajectory": trajectory,
        }
        self._write_promotion_state({
            "status": "completed" if closure["closed"] else "pending",
            "attempts": attempts + 1,
            "input_sha256": self._file_digest(self._promotion_input_path()),
            "errors": closure.get("scientific_decision", {}).get("errors", []),
            "fast_finish_eligible": self._fast_finish_eligible(closure),
            "result": (
                {
                    "round": self.round_num,
                    "signal": signal,
                    "trajectory": None,
                    "agent_result": agent_result,
                    "findings": findings_content,
                }
                if closure["closed"]
                else None
            ),
        })
        return result

    def _fast_finish_eligible(self, closure: dict) -> bool:
        """Allow fast finish only after all scientific/structural gates were audited."""
        if closure.get("closed"):
            return False
        scientific = closure.get("scientific_decision", {})
        initial_priors = closure.get("initial_priors", {})
        if not (
            scientific.get("valid")
            and initial_priors.get("valid")
            and closure.get("completed_result_files")
        ):
            return False
        if closure.get("continuation_contract_valid") is False:
            return False
        if self.round_num > 1 and not (
            closure.get("meaningful_config_change")
            and closure.get("single_config_change")
        ):
            return False
        return True

    def _existing_artifacts_fast_finish_eligible(
        self, completed_results: list[str]
    ) -> bool:
        """Re-audit deterministic artifact repairs before another LLM attempt.

        A user/controller may repair an exact machine-audit defect between attempts.
        When every scientific and structural gate now passes, the next attempt should
        perform only the bounded file-touch plus ``finish`` handshake instead of
        allowing the LLM to rewrite the already-valid decision again.
        """
        grounding_required = self.round_num == 1 and self._literature_grounding_enabled()
        closure = {
            "closed": False,
            "completed_result_files": completed_results,
            "continuation_contract_valid": (
                None if self._is_final_round() else self._continuation_contract_valid()
            ),
            "meaningful_config_change": self._meaningful_config_changed(completed_results),
            "single_config_change": self._single_config_change(completed_results)[0],
            "initial_priors": (
                self._audit_initial_priors()
                if grounding_required
                else {"valid": True, "enabled": False, "errors": []}
            ),
            "scientific_decision": self._audit_scientific_decision(None),
        }
        return self._fast_finish_eligible(closure)

    @staticmethod
    def _recovery_feedback(
        attempts: int,
        prior_closure_errors: list[str],
    ) -> str:
        if attempts <= 0:
            return ""
        if prior_closure_errors:
            rendered_errors = "\n".join(
                f"- {error}" for error in prior_closure_errors
            )
        else:
            rendered_errors = "- prior closure was incomplete; re-audit every gate"
        return (
            "\n\nThis is a controller-approved Promotion recovery attempt. "
            "The previous attempt failed closure for these exact reasons:\n"
            f"{rendered_errors}\n"
            "Correct each listed defect explicitly. Treat controller closure errors as "
            "authoritative audit feedback; do not repeat the rejected claim strength or "
            "structure."
        )

    @staticmethod
    def _fast_finish_feedback(round_num: int, attempt_num: int) -> str:
        marker = f"<!-- EVO_FAST_FINISH_RECOVERY_ATTEMPT_{attempt_num} -->"
        trace_header = f"# Round {round_num} 工作记录"
        return (
            "\n\nFAST-FINISH RECOVERY (authoritative): the scientific artifacts "
            "already passed deterministic audit and only the finish handshake is "
            "missing. Do not read any file or Skill. In your first response, issue "
            "exactly these four tool calls, with finish last: "
            f"(1) replace '{trace_header}' with '{trace_header}\\n{marker}' in "
            f"history/round{round_num}/trace.md; "
            f"(2) replace '# 研究发现' with '# 研究发现\\n{marker}' in findings.md; "
            f"(3) replace '# 研究计划' with '# 研究计划\\n{marker}' in plan.md; "
            "(4) call finish(task_completed='false') and state that the governed "
            "public round closed while final scientific success remains unclaimed. "
            "Do nothing else."
        )

    def _ensure_round_dirs(self):
        """确保本轮目录存在"""
        if not self.run_dir:
            return
        round_dir = self.run_dir / "history" / f"round{self.round_num}"
        (round_dir / "scripts").mkdir(parents=True, exist_ok=True)
        (round_dir / "results").mkdir(parents=True, exist_ok=True)

    def _promotion_input_path(self) -> Path:
        if not self.run_dir:
            raise RuntimeError("Promotion requires a run workspace")
        return self.run_dir / "history" / f"round{self.round_num}" / "promotion_input.json"

    def _promotion_state_path(self) -> Path:
        if not self.run_dir:
            raise RuntimeError("Promotion requires a run workspace")
        return self.run_dir / "history" / f"round{self.round_num}" / "promotion_state.json"

    def _promotion_evidence_path(self) -> Path:
        if not self.run_dir:
            raise RuntimeError("Promotion requires a run workspace")
        return (
            self.run_dir
            / "history"
            / f"round{self.round_num}"
            / "promotion_evidence.json"
        )

    @staticmethod
    def _compact_residual_diagnostics(payload: dict) -> dict:
        residual = (
            payload.get("verification", {})
            .get("residual_diagnostics", {})
        )
        validation = residual.get("validation", {})
        state = validation.get("state_dependence", {})
        temporal = validation.get("temporal_structure", {})
        return {
            "enabled": residual.get("enabled"),
            "status": residual.get("status"),
            "strongest_state_dependence": state.get(
                "strongest_absolute_correlation"
            ),
            "state_correlations": state.get("correlations"),
            "strongest_temporal_dependence": temporal.get(
                "strongest_reported_autocorrelation"
            ),
            "durbin_watson": temporal.get("durbin_watson"),
            "trend_correlation": temporal.get("trend_correlation"),
            "spectrum": temporal.get("spectrum"),
        }

    def _write_promotion_evidence(self, promotion_input: dict) -> dict:
        """Write a compact, controller-derived view of immutable result evidence."""
        compact_results = []
        for item in promotion_input["results"]:
            result_path = self.run_dir / item["path"]
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            compact_results.append(
                {
                    "path": item["path"],
                    "sha256": item["sha256"],
                    "experiment_id": payload.get("experiment_id"),
                    "status": payload.get("status"),
                    "config": project_meaningful_config(payload.get("config", {})),
                    "selected": payload.get("selected"),
                    "metrics": payload.get("metrics"),
                    "scale_diagnostics": (
                        payload.get("diagnostics", {})
                        .get("linear_raw_features", {})
                        .get("scale_aware")
                    ),
                    "short_ode": (
                        payload.get("verification", {}).get("short_ode")
                    ),
                    "long_horizon_dynamics": (
                        payload.get("verification", {}).get("long_horizon_dynamics")
                    ),
                    "residual_diagnostics": self._compact_residual_diagnostics(
                        payload
                    ),
                    "evaluation_budget": payload.get("evaluation_budget"),
                }
            )
        evidence = {
            "schema_version": 1,
            "round": self.round_num,
            "source": "deterministic_controller_projection_of_frozen_results",
            "full_result_read_required": False,
            "results": compact_results,
            "all_scored_results": self._all_scored_results(),
            "required_protocol_valid_result_files": [
                item["path"] for item in self._all_scored_results()
            ],
        }
        self._write_json_atomic(self._promotion_evidence_path(), evidence)
        return evidence

    def _load_or_create_promotion_input(self) -> dict:
        """Freeze completed result paths and hashes for deterministic recovery."""
        path = self._promotion_input_path()
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("round") != self.round_num:
                raise RuntimeError("Promotion input is invalid or belongs to another round")
            results = payload.get("results")
            if not isinstance(results, list) or not results:
                raise RuntimeError("Promotion input contains no frozen results")
            results_dir = self.run_dir / "history" / f"round{self.round_num}" / "results"
            for item in results:
                if not isinstance(item, dict):
                    raise RuntimeError("Promotion input result entry is invalid")
                result_path = (self.run_dir / item.get("path", "")).resolve()
                try:
                    result_path.relative_to(results_dir.resolve())
                except ValueError as exc:
                    raise RuntimeError("Frozen Promotion result escaped the current round") from exc
                if self._file_digest(result_path) != item.get("sha256"):
                    raise RuntimeError("Frozen Promotion result changed after preparation")
            self.result_files = [item["path"] for item in results]
            return payload

        if not self.result_files:
            raise RuntimeError("Promotion requires at least one completed result")
        results_dir = self.run_dir / "history" / f"round{self.round_num}" / "results"
        frozen = []
        for raw in sorted(set(self.result_files)):
            result_path = (self.run_dir / raw).resolve()
            try:
                result_path.relative_to(results_dir.resolve())
            except ValueError as exc:
                raise RuntimeError("Promotion result must stay inside the current round") from exc
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("status") != "completed":
                raise RuntimeError("Promotion result is not completed")
            frozen.append({
                "path": str(result_path.relative_to(self.run_dir)).replace("\\", "/"),
                "sha256": self._file_digest(result_path),
            })
        promotion_input = {
            "schema_version": 1,
            "round": self.round_num,
            "results": frozen,
        }
        self._write_json_atomic(path, promotion_input)
        self.result_files = [item["path"] for item in frozen]
        return promotion_input

    def _load_promotion_state(self) -> dict:
        path = self._promotion_state_path()
        if not path.is_file():
            return {"status": "pending", "attempts": 0}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("Promotion state is unreadable; refusing to reset attempts") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("Promotion state must be a JSON object")
        return payload

    def _write_promotion_state(self, payload: dict) -> None:
        self._write_json_atomic(self._promotion_state_path(), payload)

    @staticmethod
    def _write_json_atomic(path: Path, payload: dict) -> None:
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        temporary.replace(path)

    def _init_trace(self):
        """创建 L1 工作记忆 — history/round{N}/trace.md"""
        if not self.run_dir:
            return

        trace_file = self.run_dir / "history" / f"round{self.round_num}" / "trace.md"
        trace_file.parent.mkdir(parents=True, exist_ok=True)
        l1_template = f"""# 执行日志 — 第 {self.round_num} 轮

### 操作记录
（记录执行的脚本、使用的参数、观察到的现象）

### 指标记录
| 实验 | 方法 | 目标 | 关键参数 | MSE (训练) | MSE (OOD) | 方程 | 备注 |
|------|------|------|---------|-----------|-----------|------|------|

### 工作笔记
（当前假设、中间观察、思考过程）
"""
        trace_file.write_text(l1_template, encoding="utf-8")
        self.logger.info(f"创建 history/round{self.round_num}/trace.md（L1）")

    def _read_findings(self) -> str:
        """读取 findings.md（L2 知识）"""
        if not self.run_dir:
            return ""
        findings_file = self.run_dir / "findings.md"
        if findings_file.exists():
            return findings_file.read_text(encoding="utf-8")
        return ""

    def _snapshot_l2(self) -> dict:
        """记录 L2 文件的修改时间，用于 post-check"""
        if not self.run_dir:
            return {}
        snapshot = {}
        for name in ("findings.md", "plan.md"):
            path = self.run_dir / name
            if path.exists():
                snapshot[name] = path.stat().st_mtime
            else:
                snapshot[name] = 0
        return snapshot

    def _check_l2_promotion(self, before: dict) -> None:
        """检查 Agent 是否更新了 L2 文件（Phase 3 Promotion）"""
        if not self.run_dir or not before:
            return
        unchanged = []
        for name in ("findings.md", "plan.md"):
            path = self.run_dir / name
            if path.exists():
                after_mtime = path.stat().st_mtime
                if after_mtime <= before.get(name, 0):
                    unchanged.append(name)
        if unchanged:
            self.logger.warning(
                f"[Round {self.round_num}] L2 files not updated: {unchanged}. "
                "Agent may have skipped Phase 3 (Promotion). "
                "Next round will read stale L2 data."
            )

    @staticmethod
    def _file_digest(path: Path) -> str | None:
        if not path.is_file():
            return None
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _snapshot_closure_artifacts(self) -> dict:
        """Capture artifacts required to prove a single-round closed loop."""
        if not self.run_dir:
            return {}
        round_dir = self.run_dir / "history" / f"round{self.round_num}"
        results_dir = round_dir / "results"
        return {
            "trace": self._file_digest(round_dir / "trace.md"),
            "findings": self._file_digest(self.run_dir / "findings.md"),
            "plan": self._file_digest(self.run_dir / "plan.md"),
            "result_files": {
                str(path.resolve()): self._file_digest(path)
                for path in results_dir.glob("*.json")
                if path.is_file()
            },
        }

    def _completed_result_files(self, before: dict) -> list[str]:
        if not self.run_dir:
            return []
        results_dir = self.run_dir / "history" / f"round{self.round_num}" / "results"
        previous = before.get("result_files", {})
        experiment = getattr(getattr(self, "config", None), "experiment", {})
        resume_raw = (
            experiment.get("resume_completed_result")
            if isinstance(experiment, dict)
            else None
        )
        resume_path = None
        if isinstance(resume_raw, str) and resume_raw.strip():
            candidate = (self.run_dir / resume_raw).resolve()
            try:
                candidate.relative_to(results_dir.resolve())
            except ValueError:
                self.logger.warning(
                    "Ignoring resume_completed_result outside the current round results directory"
                )
            else:
                resume_path = candidate
        completed = []
        for path in results_dir.glob("*.json"):
            resolved = str(path.resolve())
            unchanged = self._file_digest(path) == previous.get(resolved)
            if unchanged and path.resolve() != resume_path:
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(payload, dict) and payload.get("status") == "completed":
                completed.append(str(path.relative_to(self.run_dir)))
        return sorted(completed)

    def _read_result_payload(self, relative_path: str) -> dict:
        if not self.run_dir:
            return {}
        try:
            payload = json.loads((self.run_dir / relative_path).read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _meaningful_config(config: dict) -> dict:
        """Legacy-compatible scientific projection without workspace policy."""
        return project_meaningful_config(config)

    def _controlled_meaningful_config(self, config: dict) -> dict:
        """Exclude identity/output fields so a renamed repeat is not treated as adaptation."""
        control = read_control(self.run_dir) if self.run_dir else None
        return project_meaningful_config(
            config,
            controller_owns_budget=bool(
                control
                and control.get("dynamic_budget", {}).get("enabled")
            ),
        )

    @staticmethod
    def _changed_config_fields(previous: object, current: object, prefix: str = "") -> list[str]:
        if isinstance(previous, dict) and isinstance(current, dict):
            fields = []
            for key in sorted(set(previous) | set(current)):
                child = f"{prefix}.{key}" if prefix else str(key)
                fields.extend(
                    PromotionExp._changed_config_fields(previous.get(key), current.get(key), child)
                )
            return fields
        return [] if previous == current else [prefix]

    def _previous_completed_configs(self) -> list[dict]:
        if not self.run_dir or self.round_num <= 1:
            return []
        state = read_state(self.run_dir)
        baseline = state.get("next_round", {}).get("baseline_result_file")
        if isinstance(baseline, str) and baseline:
            payload = self._read_result_payload(baseline)
            if payload.get("status") == "completed":
                return [
                    self._controlled_meaningful_config(
                        payload.get("config", {})
                    )
                ]
        results_dir = self.run_dir / "history" / f"round{self.round_num - 1}" / "results"
        configs = []
        for path in sorted(results_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(payload, dict) and payload.get("status") == "completed":
                configs.append(
                    self._controlled_meaningful_config(
                        payload.get("config", {})
                    )
                )
        return configs

    def _meaningful_config_changed(self, completed_results: list[str]) -> bool | None:
        if self.round_num <= 1:
            return None
        previous = self._previous_completed_configs()
        if not previous:
            return False
        current = [
            self._controlled_meaningful_config(
                self._read_result_payload(path).get("config", {})
            )
            for path in completed_results
        ]
        return any(config and config not in previous for config in current)

    def _single_config_change(self, completed_results: list[str]) -> tuple[bool | None, list[str]]:
        if self.round_num <= 1:
            return None, []
        previous = self._previous_completed_configs()
        current = [
            self._controlled_meaningful_config(
                self._read_result_payload(path).get("config", {})
            )
            for path in completed_results
        ]
        if not previous or len(current) != 1:
            return False, []
        changed = self._changed_config_fields(previous[-1], current[0])
        control = read_control(self.run_dir) if self.run_dir else None
        max_step_changes = int(
            (control or {}).get("trust_region", {}).get(
                "max_step_changes", 1
            )
        )
        return 1 <= len(changed) <= max_step_changes, changed

    def _continuation_contract_valid(self) -> bool:
        if not self.run_dir:
            return False
        plan_path = self.run_dir / "plan.md"
        if not plan_path.is_file():
            return False
        content = plan_path.read_text(encoding="utf-8")
        if NEXT_ROUND_BEGIN not in content or NEXT_ROUND_END not in content:
            return False
        start = content.index(NEXT_ROUND_BEGIN)
        end = content.index(NEXT_ROUND_END, start)
        contract = content[start:end]
        for field in NEXT_ROUND_FIELDS:
            contract = re.sub(
                rf"(?m)^([ \t]*-[ \t]*{re.escape(field)})"
                rf"[（(][^\r\n]*?[）)]",
                r"\1",
                contract,
            )
        return all(
            re.search(
                rf"(?m)^[ \t]*-[ \t]*{re.escape(field)}"
                rf"(?:（[^\r\n]*?）)?[ \t]*[：:][ \t]*\S.*$",
                contract,
            )
            is not None
            for field in NEXT_ROUND_FIELDS
        )

    def _is_final_round(self) -> bool:
        experiment = getattr(getattr(self, "config", None), "experiment", {})
        if not isinstance(experiment, dict):
            experiment = vars(experiment) if experiment is not None else {}
        try:
            max_rounds = int(experiment.get("max_rounds", 0) or 0)
        except (TypeError, ValueError):
            return False
        return max_rounds > 0 and self.round_num >= max_rounds

    @staticmethod
    def _normalize_result_path(path: object) -> str:
        return str(path or "").replace("\\", "/").lstrip("./")

    def _all_scored_results(self) -> list[dict]:
        if not self.run_dir:
            return []
        scored = []
        for path in sorted((self.run_dir / "history").glob("round*/results/*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                score = float(payload["selected"]["scientific_score"])
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
                continue
            if payload.get("status") != "completed" or not math.isfinite(score):
                continue
            scored.append(
                {
                    "path": self._normalize_result_path(path.relative_to(self.run_dir)),
                    "score": score,
                    "equation": payload.get("selected", {}).get("simplified_equation"),
                }
            )
        return scored

    def _read_scientific_decision(self) -> tuple[dict | None, str | None]:
        if not self.run_dir:
            return None, "workspace unavailable"
        plan_path = self.run_dir / "plan.md"
        if not plan_path.is_file():
            return None, "plan.md missing"
        content = plan_path.read_text(encoding="utf-8")
        if SCIENTIFIC_DECISION_BEGIN not in content or SCIENTIFIC_DECISION_END not in content:
            return None, "scientific decision block missing"
        start = content.index(SCIENTIFIC_DECISION_BEGIN) + len(SCIENTIFIC_DECISION_BEGIN)
        end = content.index(SCIENTIFIC_DECISION_END, start)
        raw = content[start:end].strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(lines[1:-1]).strip()
        try:
            decision = json.loads(raw)
        except json.JSONDecodeError as exc:
            return None, f"scientific decision JSON invalid: {exc}"
        return (decision, None) if isinstance(decision, dict) else (None, "decision must be an object")

    @staticmethod
    def _parse_last_json_block(
        content: str,
        begin_marker: str,
        end_marker: str,
        label: str,
    ) -> tuple[dict | None, str | None]:
        start_marker = content.rfind(begin_marker)
        if start_marker < 0:
            return None, f"{label} block missing"
        start = start_marker + len(begin_marker)
        end = content.find(end_marker, start)
        if end < 0:
            return None, f"{label} block is not terminated"
        raw = content[start:end].strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(lines[1:-1]).strip()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            return None, f"{label} JSON invalid: {exc}"
        return (
            (payload, None)
            if isinstance(payload, dict)
            else (None, f"{label} must be an object")
        )

    @staticmethod
    def _same_optional_number(recorded: object, actual: object) -> bool:
        if recorded is None or actual is None:
            return recorded is None and actual is None
        if isinstance(recorded, bool) or isinstance(actual, bool):
            return False
        try:
            recorded_number = float(recorded)
            actual_number = float(actual)
        except (TypeError, ValueError):
            return False
        return (
            math.isfinite(recorded_number)
            and math.isfinite(actual_number)
            and math.isclose(recorded_number, actual_number, rel_tol=1e-9, abs_tol=1e-12)
        )

    def _audit_residual_feedback(self) -> dict:
        """Verify that findings.md faithfully promotes current-round residual evidence."""
        audit = {"valid": False, "errors": [], "result_file": None}
        if not self.run_dir:
            audit["errors"].append("workspace unavailable")
            return audit
        findings_path = self.run_dir / "findings.md"
        if not findings_path.is_file():
            audit["errors"].append("findings.md missing")
            return audit
        feedback, parse_error = self._parse_last_json_block(
            findings_path.read_text(encoding="utf-8"),
            RESIDUAL_FEEDBACK_BEGIN,
            RESIDUAL_FEEDBACK_END,
            "residual feedback",
        )
        if parse_error:
            audit["errors"].append(parse_error)
            return audit

        if feedback.get("round") != self.round_num:
            audit["errors"].append("residual feedback does not belong to the current round")
        result_file = self._normalize_result_path(feedback.get("result_file"))
        audit["result_file"] = result_file
        current_prefix = f"history/round{self.round_num}/results/"
        current_results = {
            self._normalize_result_path(path.relative_to(self.run_dir))
            for path in (
                self.run_dir / "history" / f"round{self.round_num}" / "results"
            ).glob("*.json")
            if path.is_file()
        }
        if not result_file.startswith(current_prefix) or result_file not in current_results:
            audit["errors"].append("residual feedback must cite a current-round result")
            return audit
        promotion_input_path = self._promotion_input_path()
        if promotion_input_path.is_file():
            try:
                promotion_input = json.loads(
                    promotion_input_path.read_text(encoding="utf-8")
                )
                frozen_results = {
                    self._normalize_result_path(item.get("path"))
                    for item in promotion_input.get("results", [])
                    if isinstance(item, dict)
                }
            except (OSError, json.JSONDecodeError, AttributeError):
                frozen_results = set()
            if result_file not in frozen_results:
                audit["errors"].append(
                    "residual feedback result is not frozen in promotion_input.json"
                )
                return audit
        result = self._read_result_payload(result_file)
        residual = result.get("verification", {}).get("residual_diagnostics", {})
        if (
            result.get("status") != "completed"
            or residual.get("enabled") is not True
            or residual.get("status") != "completed"
        ):
            audit["errors"].append(
                "current result lacks enabled, completed residual diagnostics"
            )
            return audit

        validation = residual.get("validation", {})
        actual_state = (
            validation.get("state_dependence", {})
            .get("strongest_absolute_correlation", {})
        )
        recorded_state = feedback.get("strongest_state_dependence")
        if not isinstance(recorded_state, dict) or (
            recorded_state.get("signal") != actual_state.get("signal")
            or not self._same_optional_number(
                recorded_state.get("value"),
                actual_state.get("value"),
            )
        ):
            audit["errors"].append(
                "findings residual state dependence does not match the result JSON"
            )

        actual_temporal = (
            validation.get("temporal_structure", {})
            .get("strongest_reported_autocorrelation", {})
        )
        recorded_temporal = feedback.get("strongest_temporal_dependence")
        if not isinstance(recorded_temporal, dict) or (
            recorded_temporal.get("lag") != actual_temporal.get("lag")
            or not self._same_optional_number(
                recorded_temporal.get("value"),
                actual_temporal.get("value"),
            )
        ):
            audit["errors"].append(
                "findings residual temporal dependence does not match the result JSON"
            )

        for field in ("interpretation", "next_testable_question"):
            if not isinstance(feedback.get(field), str) or not feedback[field].strip():
                audit["errors"].append(f"residual feedback {field} is missing")
        alternatives = feedback.get("alternative_explanations")
        if not isinstance(alternatives, list) or not alternatives or not all(
            isinstance(item, str) and item.strip() for item in alternatives
        ):
            audit["errors"].append(
                "residual feedback needs at least one alternative explanation"
            )
        limitations = feedback.get("limitations")
        if not isinstance(limitations, list) or not limitations or not all(
            isinstance(item, str) and item.strip() for item in limitations
        ):
            audit["errors"].append("residual feedback needs explicit limitations")

        audit["valid"] = not audit["errors"]
        return audit

    @staticmethod
    def _evidence_gates_valid(gates: object) -> bool:
        if not isinstance(gates, list) or not gates:
            return False
        return all(
            isinstance(gate, dict)
            and isinstance(gate.get("name"), str)
            and bool(gate["name"].strip())
            and isinstance(gate.get("passed"), bool)
            and isinstance(gate.get("evidence"), str)
            and bool(gate["evidence"].strip())
            for gate in gates
        )

    def _audit_scientific_decision(self, task_completed: str | None) -> dict:
        """Audit incumbent retention, claim strength, scaling, planning, and success gates."""
        decision, parse_error = self._read_scientific_decision()
        audit = {
            "valid": False,
            "errors": [parse_error] if parse_error else [],
            "incumbent_valid": False,
            "claims_valid": False,
            "scale_diagnostics_valid": False,
            "residual_feedback_valid": False,
            "protocol_evidence_valid": False,
            "plan_quality_valid": False,
            "success_gates_valid": False,
        }
        if decision is None:
            return audit

        search_advancement_gates = decision.get("search_advancement_gates")
        legacy_promotion_gates = decision.get("promotion_gates")
        if search_advancement_gates is None:
            search_advancement_gates = legacy_promotion_gates
        search_advancement_gates_valid = self._evidence_gates_valid(
            search_advancement_gates
        )
        audit["search_advancement_gates_valid"] = (
            search_advancement_gates_valid
        )
        # Compatibility alias for completed historical workspaces and callers.
        audit["promotion_gates_valid"] = search_advancement_gates_valid
        if not search_advancement_gates_valid:
            audit["errors"].append(
                "search advancement gates are missing or unsupported"
            )

        scored = self._all_scored_results()
        if not scored:
            audit["errors"].append("no completed result with a finite scientific score")
        else:
            current_prefix = f"history/round{self.round_num}/"
            current = [item for item in scored if item["path"].startswith(current_prefix)]
            prior = [item for item in scored if not item["path"].startswith(current_prefix)]
            current_best = min(current, key=lambda item: item["score"]) if current else None
            prior_best = min(prior, key=lambda item: item["score"]) if prior else None
            current_passes = search_advancement_gates_valid and all(
                gate["passed"] for gate in search_advancement_gates
            )
            control = read_control(self.run_dir) if self.run_dir else None
            min_improvement = float(
                (control or {})
                .get("search_advancement", {})
                .get("min_score_improvement", 0.0)
            )
            if prior_best is None:
                best = current_best
                expected_action = "initialize"
            elif (
                current_best is not None
                and current_best["score"]
                < prior_best["score"] - min_improvement
                and current_passes
            ):
                best = current_best
                expected_action = "promote"
            else:
                best = prior_best
                expected_action = "retain"
            chosen = self._normalize_result_path(decision.get("incumbent", {}).get("result_file"))
            action = decision.get("incumbent", {}).get("action")
            audit["incumbent_expected"] = best
            audit["incumbent_action_expected"] = expected_action
            audit["incumbent_valid"] = (
                best is not None and chosen == best["path"] and action == expected_action
            )
            if not audit["incumbent_valid"] and best is not None:
                audit["errors"].append(
                    f"incumbent must {expected_action}: {best['path']}"
                )

        claims = decision.get("claims")
        claims_valid = isinstance(claims, list) and bool(claims)
        if claims_valid:
            for claim in claims:
                if not isinstance(claim, dict):
                    claims_valid = False
                    break
                strength = claim.get("strength")
                evidence = claim.get("evidence")
                if strength not in ALLOWED_CLAIM_STRENGTHS or not isinstance(evidence, list) or not evidence:
                    claims_valid = False
                    break
                if strength == "confirmed" and (
                    len(evidence) < 2 or int(claim.get("alternatives_tested", 0) or 0) < 1
                ):
                    claims_valid = False
                    break
        audit["claims_valid"] = claims_valid
        if not claims_valid:
            audit["errors"].append("claims lack evidence or overstate confirmation")

        protocol_evidence = decision.get("protocol_evidence")
        expected_valid_results = {item["path"] for item in scored}
        declared_valid_results = []
        if isinstance(protocol_evidence, dict):
            raw_declared = protocol_evidence.get("valid_result_files")
            if isinstance(raw_declared, list):
                declared_valid_results = [
                    self._normalize_result_path(path)
                    for path in raw_declared
                    if isinstance(path, str) and path.strip()
                ]
        protocol_evidence_valid = (
            isinstance(protocol_evidence, dict)
            and protocol_evidence.get(
                "invalid_attempts_used_as_scientific_evidence"
            )
            is False
            and len(declared_valid_results) == len(set(declared_valid_results))
            and set(declared_valid_results) == expected_valid_results
        )
        audit["protocol_evidence_valid"] = protocol_evidence_valid
        if not protocol_evidence_valid:
            audit["errors"].append(
                "protocol evidence must enumerate exactly the completed valid-round "
                "results and explicitly exclude invalid attempts from scientific evidence"
            )

        scale = decision.get("scale_diagnostics")
        scale_valid = (
            isinstance(scale, dict)
            and scale.get("method") in ALLOWED_SCALE_METHODS
            and scale.get("raw_coefficient_comparison") is False
            and isinstance(scale.get("evidence"), str)
            and bool(scale["evidence"].strip())
        )
        audit["scale_diagnostics_valid"] = scale_valid
        if not scale_valid:
            audit["errors"].append("scale diagnostics compare raw cross-unit coefficients")

        residual_feedback = self._audit_residual_feedback()
        audit["residual_feedback"] = residual_feedback
        audit["residual_feedback_valid"] = residual_feedback["valid"]
        audit["errors"].extend(residual_feedback["errors"])

        gates = decision.get("scientific_gates")
        scientific_incomplete = (
            not self._evidence_gates_valid(gates)
            or not all(gate["passed"] for gate in gates)
        )
        continuing = task_completed in {"false", "partial"} or scientific_incomplete
        if continuing:
            strategy = decision.get("next_strategy")
            required = (
                "diagnosed_failure",
                "evidence",
                "config_field",
                "expected_effect",
                "alternative_explanation",
                "expected_residual_change",
                "falsification",
            )
            strategy_valid = isinstance(strategy, dict) and all(
                isinstance(strategy.get(field), str) and bool(strategy[field].strip())
                for field in required
            )
            strategy_valid = (
                strategy_valid
                and isinstance(strategy.get("risks"), list)
                and bool(strategy["risks"])
                and all(isinstance(risk, str) and risk.strip() for risk in strategy["risks"])
                and re.fullmatch(
                    r"(?:data|search|verification)(?:\.[A-Za-z0-9_]+)+",
                    strategy.get("config_field", ""),
                )
                is not None
            )
            config_patch = (
                strategy.get("config_patch")
                if isinstance(strategy, dict)
                else None
            )
            strategy_valid = (
                strategy_valid
                and isinstance(config_patch, dict)
                and len(config_patch) == 1
                and next(iter(config_patch), None) == strategy.get("config_field")
            )
            residual_evidence = (
                strategy.get("residual_evidence")
                if isinstance(strategy, dict)
                else None
            )
            strategy_valid = (
                strategy_valid
                and isinstance(residual_evidence, dict)
                and self._normalize_result_path(residual_evidence.get("result_file"))
                == residual_feedback.get("result_file")
                and residual_evidence.get("finding")
                in {
                    "state_dependence",
                    "temporal_dependence",
                    "both",
                    "no_material_structure",
                }
                and isinstance(residual_evidence.get("observed"), str)
                and bool(residual_evidence["observed"].strip())
            )
        else:
            strategy_valid = True
        audit["plan_quality_valid"] = strategy_valid
        if not strategy_valid:
            audit["errors"].append(
                "next strategy lacks linked residual evidence, alternative explanation, "
                "expected residual change, risk, or falsification"
            )

        gates_valid = self._evidence_gates_valid(gates)
        if task_completed == "true":
            gates_valid = (
                gates_valid
                and all(gate["passed"] for gate in gates)
                and decision.get("solver_completion_only") is False
            )
        audit["success_gates_valid"] = gates_valid
        if not gates_valid:
            audit["errors"].append("scientific success gates are missing, unsupported, or solver-only")

        audit["valid"] = all(
            audit[key]
            for key in (
                "incumbent_valid",
                "search_advancement_gates_valid",
                "claims_valid",
                "scale_diagnostics_valid",
                "residual_feedback_valid",
                "protocol_evidence_valid",
                "plan_quality_valid",
                "success_gates_valid",
            )
        )
        return audit

    def _scientific_governance_enabled(self) -> bool:
        experiment = getattr(getattr(self, "config", None), "experiment", {})
        return isinstance(experiment, dict) and bool(experiment.get("scientific_governance", False))

    def _literature_grounding_enabled(self) -> bool:
        experiment = getattr(getattr(self, "config", None), "experiment", {})
        return isinstance(experiment, dict) and bool(
            experiment.get("require_literature_grounding", False)
        )

    def _audit_initial_priors(self) -> dict:
        audit = {"valid": False, "errors": []}
        if not self.run_dir:
            audit["errors"].append("workspace unavailable")
            return audit
        plan_path = self.run_dir / "plan.md"
        if not plan_path.is_file():
            audit["errors"].append("plan.md missing")
            return audit
        content = plan_path.read_text(encoding="utf-8")
        if INITIAL_PRIORS_BEGIN not in content or INITIAL_PRIORS_END not in content:
            audit["errors"].append("initial literature priors block missing")
            return audit
        start = content.index(INITIAL_PRIORS_BEGIN) + len(INITIAL_PRIORS_BEGIN)
        end = content.index(INITIAL_PRIORS_END, start)
        raw = content[start:end].strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(lines[1:-1]).strip()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            audit["errors"].append(f"initial priors JSON invalid: {exc}")
            return audit

        queries = payload.get("queries")
        sources = payload.get("sources")
        priors = payload.get("priors")
        source_ids = {
            item.get("id")
            for item in sources or []
            if isinstance(item, dict)
            and isinstance(item.get("id"), str)
            and item.get("title")
            and item.get("url")
        }
        if payload.get("status") != "completed":
            audit["errors"].append("initial literature grounding is not completed")
        if not isinstance(queries, list) or len(queries) < 2 or not all(
            isinstance(item, str) and item.strip() for item in queries
        ):
            audit["errors"].append("at least two broad literature queries are required")
        if not isinstance(sources, list) or len(source_ids) < 2:
            audit["errors"].append("at least two cited literature sources are required")
        priors_valid = isinstance(priors, list) and len(priors) >= 3
        if priors_valid:
            for prior in priors:
                evidence = prior.get("evidence_sources") if isinstance(prior, dict) else None
                statement = prior.get("statement") if isinstance(prior, dict) else None
                strength = prior.get("strength") if isinstance(prior, dict) else None
                if (
                    not isinstance(statement, str)
                    or not statement.strip()
                    or "=" in statement
                    or "^" in statement
                    or not isinstance(evidence, list)
                    or not evidence
                    or not set(evidence).issubset(source_ids)
                    or strength not in {"hypothesis", "supported"}
                ):
                    priors_valid = False
                    break
        if not priors_valid:
            audit["errors"].append(
                "initial priors need three cited qualitative statements without equation syntax"
            )
        if payload.get("candidate_template_proposed") is not False:
            audit["errors"].append("candidate_template_proposed must be false")
        audit["valid"] = not audit["errors"]
        return audit

    def _check_round_closure(
        self,
        before: dict,
        trajectory,
        completed_results: list[str] | None = None,
    ) -> dict:
        """Return machine-readable proof that all phases of the round completed."""
        if not self.run_dir or not before:
            return {
                "closed": False,
                "finish_called": False,
                "trace_updated": False,
                "findings_updated": False,
                "plan_updated": False,
                "completed_result_files": [],
                "continuation_contract_valid": None,
                "meaningful_config_change": None,
                "scientific_decision": {"valid": False, "errors": ["closure snapshot unavailable"]},
            }

        round_dir = self.run_dir / "history" / f"round{self.round_num}"
        if completed_results is None:
            completed_results = self._completed_result_files(before)
        task_completed = self._extract_task_completed(trajectory)
        continuing = (
            task_completed in {"false", "partial"}
            and not self._is_final_round()
        )
        continuation_contract_valid = self._continuation_contract_valid() if continuing else None
        meaningful_config_change = self._meaningful_config_changed(completed_results)
        single_config_change, changed_config_fields = self._single_config_change(completed_results)
        governance_enabled = self._scientific_governance_enabled()
        grounding_required = self.round_num == 1 and self._literature_grounding_enabled()
        initial_priors = (
            self._audit_initial_priors()
            if grounding_required
            else {"valid": True, "enabled": False, "errors": []}
        )
        scientific_decision = (
            self._audit_scientific_decision(task_completed)
            if governance_enabled
            else {"valid": True, "enabled": False, "errors": []}
        )
        closure = {
            "finish_called": task_completed is not None,
            "trace_updated": self._file_digest(round_dir / "trace.md") != before.get("trace"),
            "findings_updated": self._file_digest(self.run_dir / "findings.md") != before.get("findings"),
            "plan_updated": self._file_digest(self.run_dir / "plan.md") != before.get("plan"),
            "completed_result_files": completed_results,
            "continuation_contract_valid": continuation_contract_valid,
            "meaningful_config_change": meaningful_config_change,
            "single_config_change": single_config_change,
            "changed_config_fields": changed_config_fields,
            "initial_priors": initial_priors,
            "scientific_decision": scientific_decision,
        }
        requirements = [
            closure["finish_called"],
            closure["trace_updated"],
            closure["findings_updated"],
            closure["plan_updated"],
            bool(completed_results),
            initial_priors["valid"],
            scientific_decision["valid"],
        ]
        if continuing:
            requirements.append(bool(continuation_contract_valid))
        if self.round_num > 1:
            requirements.append(bool(meaningful_config_change))
            requirements.append(bool(single_config_change))
        closure["closed"] = all(requirements)
        if closure["closed"]:
            self.logger.info(f"[Round {self.round_num}] Closed-loop proof: {closure}")
        else:
            self.logger.warning(f"[Round {self.round_num}] Closure incomplete: {closure}")
        return closure

    def _extract_agent_response(self, trajectory) -> str:
        return super()._extract_agent_response(trajectory)

    # =========================
    # Signal parsing
    # =========================

    def _parse_signal(self, agent_message: str, trajectory) -> dict:
        """Parse signal from finish tool's task_completed parameter.

        The Agent calls finish(message=..., task_completed="true"/"false").
        task_completed="true" → satisfied=True (stop iterating).
        task_completed="false" → satisfied=False (continue).
        """
        task_completed = self._extract_task_completed(trajectory)

        if task_completed is None:
            self.logger.warning(
                f"[Round {self.round_num}] Could not extract task_completed from trajectory. "
                "Agent may not have called finish(). Defaulting to satisfied=False."
            )
            return {"round": self.round_num, "satisfied": False}

        satisfied = task_completed == "true"

        # Extract finish message for logging
        finish_message = self._extract_finish_message_from_trajectory(trajectory)

        return {
            "round": self.round_num,
            "satisfied": satisfied,
            "task_completed": task_completed,
            "notes": finish_message[:500] if finish_message else "",
        }

    def _extract_task_completed(self, trajectory) -> str | None:
        """Extract task_completed value from the finish tool call in trajectory."""
        try:
            steps = getattr(trajectory, "steps", None)
            if not isinstance(steps, list):
                return None
            for step in reversed(steps):
                assistant_message = getattr(step, "assistant_message", None)
                tool_calls = getattr(assistant_message, "tool_calls", None)
                if not tool_calls:
                    continue
                for tc in reversed(tool_calls):
                    fn = getattr(tc, "function", None)
                    if not fn or getattr(fn, "name", None) != "finish":
                        continue
                    args = getattr(fn, "arguments", "") or ""
                    try:
                        parsed = json.loads(args) if isinstance(args, str) and args.strip() else {}
                    except Exception:
                        return None
                    if isinstance(parsed, dict):
                        return parsed.get("task_completed")
        except Exception:
            return None
        return None

    def _extract_finish_message_from_trajectory(self, trajectory) -> str:
        """Extract finish.message from trajectory (robust fallback)."""
        try:
            steps = getattr(trajectory, "steps", None)
            if not isinstance(steps, list):
                return ""
            for step in reversed(steps):
                assistant_message = getattr(step, "assistant_message", None)
                tool_calls = getattr(assistant_message, "tool_calls", None)
                if not tool_calls:
                    continue
                for tc in reversed(tool_calls):
                    fn = getattr(tc, "function", None)
                    if not fn or getattr(fn, "name", None) != "finish":
                        continue
                    args = getattr(fn, "arguments", "") or ""
                    try:
                        parsed = json.loads(args) if isinstance(args, str) and args.strip() else {}
                    except Exception:
                        return args
                    if isinstance(parsed, dict):
                        msg = parsed.get("message")
                        if isinstance(msg, str):
                            return msg
                        return json.dumps(parsed, ensure_ascii=False)
                    return str(parsed)
        except Exception:
            return ""
        return ""
