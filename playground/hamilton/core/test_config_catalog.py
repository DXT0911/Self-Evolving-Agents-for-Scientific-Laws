"""Offline consistency checks for the Hamilton configuration catalog."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = PROJECT_ROOT / "configs" / "hamilton"
PROMPT_DIR = PROJECT_ROOT / "playground" / "hamilton" / "prompts"


class HamiltonConfigCatalogTests(unittest.TestCase):
    def test_all_configured_prompts_exist_in_runtime_prompt_tree(self) -> None:
        for config_path in sorted(CONFIG_DIR.glob("config*.yaml")):
            with self.subTest(config=config_path.name):
                payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
                agents = payload.get("agents", {})
                self.assertIsInstance(agents, dict)
                for agent in agents.values():
                    for key in ("system_prompt_file", "user_prompt_file"):
                        relative_path = agent.get(key)
                        if not relative_path:
                            continue
                        prompt_path = PROMPT_DIR.parent / relative_path
                        self.assertTrue(
                            prompt_path.is_file(),
                            f"{config_path.name}: missing runtime prompt {relative_path}",
                        )

    def test_configs_do_not_contain_a_second_prompt_tree(self) -> None:
        duplicate_prompt_dir = CONFIG_DIR / "prompts"
        duplicate_files = (
            list(duplicate_prompt_dir.iterdir()) if duplicate_prompt_dir.is_dir() else []
        )
        self.assertEqual(
            duplicate_files,
            [],
            "Hamilton prompts have one source of truth under playground/hamilton/prompts",
        )


if __name__ == "__main__":
    unittest.main()
