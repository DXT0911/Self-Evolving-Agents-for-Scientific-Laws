from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from playground.hamilton.core.findings_writer import render_findings, write_findings


class FindingsWriterTests(unittest.TestCase):
    def test_findings_contains_facts_and_llm_decision(self) -> None:
        rounds = [{
            "round": 1,
            "binding_action": {"action": "initialize", "config_patch": {}},
            "selected_equation": "x1 * x2**2",
            "selected_score": 0.031,
            "incumbent_action": "initialize",
            "engine_measured_evaluations": 1500,
            "attempts": 1,
            "llm_decision": {
                "planner_status": "accepted",
                "hypothesis": "residual structure may need more complexity",
                "rationale": "structured residual remains",
                "expected_effect": "lower validation error",
                "falsification": "score does not improve",
                "selected_action": {
                    "action": "modify",
                    "config_patch": {"search.parsimony": 0.005},
                },
            },
        }]
        text = render_findings(
            rounds=rounds,
            incumbent={
                "score": 0.031,
                "equation": "x1 * x2**2",
                "result_file": "history/round1/results/result.json",
            },
            status="running",
        )
        self.assertIn("x1 * x2**2", text)
        self.assertIn("0.031", text)
        self.assertIn("search.parsimony=0.005", text)
        self.assertNotIn("请在此处填写", text)

    def test_writer_replaces_an_existing_template(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            (workspace / "findings.md").write_text("template", encoding="utf-8")
            write_findings(
                workspace,
                rounds=[],
                incumbent=None,
                status="initialized",
            )
            self.assertIn("Hamilton 符号回归发现", (workspace / "findings.md").read_text(encoding="utf-8"))
            self.assertFalse((workspace / "findings.md.tmp").exists())


if __name__ == "__main__":
    unittest.main()
