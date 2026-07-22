"""Hamilton discovery and verification experiment.

`RoundExp` is intentionally limited to the evidence-producing part of a round. Scientific
Promotion, L2 updates, and the final closure audit live in `PromotionExp`.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from evomaster.agent import BaseAgent
from evomaster.core.exp import BaseExp
from evomaster.utils.types import TaskInstance


class RoundExp(BaseExp):
    """Run Discovery and Verification and return newly completed result files."""

    def __init__(self, agent, config, round_num):
        super().__init__(agent, config)
        self.round_num = round_num
        self.logger = logging.getLogger(self.__class__.__name__)

    @property
    def exp_name(self) -> str:
        return f"Round_{self.round_num}"

    @staticmethod
    def _file_digest(path: Path) -> str | None:
        if not path.is_file():
            return None
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _round_dir(self) -> Path:
        if not self.run_dir:
            raise RuntimeError("RoundExp requires a run workspace")
        return self.run_dir / "history" / f"round{self.round_num}"

    def _ensure_round_dirs(self) -> None:
        round_dir = self._round_dir()
        (round_dir / "scripts").mkdir(parents=True, exist_ok=True)
        (round_dir / "results").mkdir(parents=True, exist_ok=True)

    def _init_trace(self) -> None:
        trace_path = self._round_dir() / "trace.md"
        trace_path.write_text(
            f"# Round {self.round_num} 工作记录\n\n"
            "## Discovery / Verification\n\n"
            "（由 Agent 记录本轮假设、实验配置、结果与验证证据）\n\n"
            "## Promotion\n\n"
            "（由后续 PromotionExp 更新）\n",
            encoding="utf-8",
        )

    def _result_snapshot(self) -> dict[str, str | None]:
        results_dir = self._round_dir() / "results"
        return {
            str(path.resolve()): self._file_digest(path)
            for path in results_dir.glob("*.json")
            if path.is_file()
        }

    def _new_completed_results(self, before: dict[str, str | None]) -> list[str]:
        completed = []
        for path in (self._round_dir() / "results").glob("*.json"):
            resolved = str(path.resolve())
            if self._file_digest(path) == before.get(resolved):
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict) and payload.get("status") == "completed":
                completed.append(str(path.relative_to(self.run_dir)).replace("\\", "/"))
        return sorted(completed)

    def run(self, task_description: str, task_id: str = "exp_001") -> dict:
        self.logger.info("Starting Discovery/Verification for Round %s", self.round_num)
        BaseAgent.set_exp_info(exp_name=self.exp_name, exp_index=self.round_num)
        self._ensure_round_dirs()
        self._init_trace()
        before = self._result_snapshot()

        task = TaskInstance(
            task_id=f"{task_id}_round{self.round_num}_discovery",
            task_type="hamilton_round",
            description=(
                f"{task_description}\n\n"
                "Execute Literature Grounding when required, Discovery, and Verification "
                "only. Produce a completed result JSON and update trace.md. Do not perform "
                "Promotion or update the EVO_SCIENTIFIC_DECISION block; call finish with "
                "task_completed=false after verification."
            ),
            input_data={"round": self.round_num, "phase": "discovery_verification"},
        )
        trajectory = self.agent.run(task)
        completed_results = self._new_completed_results(before)
        return {
            "round": self.round_num,
            "agent_result": self._extract_agent_response(trajectory),
            "completed_result_files": completed_results,
            "ready_for_promotion": bool(completed_results),
            "trajectory": trajectory,
        }
