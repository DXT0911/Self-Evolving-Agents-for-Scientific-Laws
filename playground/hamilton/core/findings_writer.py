"""Deterministic Markdown findings for LLM-led Hamilton searches."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _display(value: object, default: str = "unknown") -> str:
    if value is None:
        return default
    if isinstance(value, float):
        return f"{value:.12g}"
    return str(value)


def _action_text(action: object) -> str:
    if not isinstance(action, dict):
        return "unknown"
    name = str(action.get("action", "unknown"))
    patch = action.get("config_patch")
    if isinstance(patch, dict) and patch:
        updates = ", ".join(f"{key}={_display(value)}" for key, value in patch.items())
        return f"{name} ({updates})"
    return name


def render_findings(
    *,
    rounds: list[dict[str, Any]],
    incumbent: dict[str, Any] | None,
    status: str,
    stop_reason: str | None = None,
) -> str:
    """Render factual results and clearly labelled LLM interpretations."""
    lines = [
        "# Hamilton 符号回归发现",
        "",
        "> 数值、方程和评估次数来自已完成的 result.json；假设、理由和证伪条件来自 LLM。",
        "",
        "## 当前结论",
        "",
        f"- 状态：{status}",
        f"- 已完成轮数：{len(rounds)}",
    ]
    if incumbent:
        lines.extend([
            f"- 当前最佳 scientific score：{_display(incumbent.get('score'))}（越小越好）",
            f"- 当前最佳方程：`{_display(incumbent.get('equation'))}`",
            f"- 最佳结果文件：`{_display(incumbent.get('result_file'))}`",
        ])
    if stop_reason:
        lines.append(f"- 停止原因：{stop_reason}")

    for record in rounds:
        round_num = int(record.get("round", 0) or 0)
        decision = record.get("llm_decision")
        decision = decision if isinstance(decision, dict) else {}
        feedback = record.get("llm_feedback")
        feedback = feedback if isinstance(feedback, dict) else {}
        lines.extend([
            "",
            f"## Round {round_num}",
            "",
            "### 实验事实",
            "",
            f"- 本轮实际动作：{_action_text(record.get('binding_action'))}",
            f"- 本轮方程：`{_display(record.get('selected_equation'))}`",
            f"- 本轮 scientific score：{_display(record.get('selected_score'))}",
            f"- 最佳方程处理：{_display(record.get('incumbent_action'))}",
            f"- 本轮引擎 evaluations：{_display(record.get('engine_measured_evaluations'))}",
            f"- 执行尝试次数：{_display(record.get('attempts'))}",
            "",
            "### LLM 下一步判断",
            "",
            f"- Planner 状态：{_display(decision.get('planner_status'), 'not_called')}",
            f"- 假设：{_display(decision.get('hypothesis'), '本轮结束后未调用 Planner')}",
            f"- 选择：{_action_text(decision.get('selected_action'))}",
            f"- 理由：{_display(decision.get('rationale'))}",
            f"- 预期效果：{_display(decision.get('expected_effect'))}",
            f"- 证伪条件：{_display(decision.get('falsification'))}",
            f"- 下一轮验证状态：{_display(feedback.get('status'), '尚未经过下一轮验证')}",
            f"- 验证时 score 改善量：{_display(feedback.get('score_improvement'))}",
            f"- 验证时残差相关性下降量：{_display(feedback.get('residual_correlation_reduction'))}",
        ])

    lines.extend([
        "",
        "## 解释边界",
        "",
        "- LLM 的假设是下一轮搜索策略，不是已经证明的科学规律。",
        "- 最佳结论必须以验证集、残差诊断和重复实验为准。",
        "- Planner 失败时采用的 deterministic fallback 会在对应轮次明确标出。",
        "",
    ])
    return "\n".join(lines)


def write_findings(
    workspace: Path,
    *,
    rounds: list[dict[str, Any]],
    incumbent: dict[str, Any] | None,
    status: str,
    stop_reason: str | None = None,
) -> Path:
    """Atomically replace the template with evidence-backed findings."""
    path = workspace / "findings.md"
    temporary = path.with_suffix(".md.tmp")
    temporary.write_text(
        render_findings(
            rounds=rounds,
            incumbent=incumbent,
            status=status,
            stop_reason=stop_reason,
        ),
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return path
