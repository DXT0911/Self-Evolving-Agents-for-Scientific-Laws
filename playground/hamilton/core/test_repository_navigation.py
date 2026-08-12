"""Offline repository-navigation and artifact-boundary contracts."""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from urllib.parse import unquote


PROJECT_ROOT = Path(__file__).resolve().parents[3]
LOCAL_LINK = re.compile(r"(?<!!)\[[^]]*\]\(([^)]+)\)")


class RepositoryNavigationTests(unittest.TestCase):
    def test_authoritative_navigation_documents_have_no_broken_local_links(self) -> None:
        documents = [
            PROJECT_ROOT / "README.md",
            PROJECT_ROOT / "README-zh.md",
            PROJECT_ROOT / "WORKSPACE.md",
            PROJECT_ROOT / "WORKSPACE.zh-CN.md",
            PROJECT_ROOT / "playground" / "README.md",
            PROJECT_ROOT / "playground" / "README_CN.md",
            PROJECT_ROOT / "playground" / "hamilton" / "README.md",
            PROJECT_ROOT / "playground" / "hamilton" / "DEVELOPMENT.md",
            PROJECT_ROOT / "playground" / "hamilton" / "DEVELOPMENT.zh-CN.md",
            PROJECT_ROOT / "configs" / "hamilton" / "README.md",
            PROJECT_ROOT / "configs" / "hamilton" / "README.zh-CN.md",
            PROJECT_ROOT / "docs" / "sragent" / "README.md",
            PROJECT_ROOT / "docs" / "sragent" / "README.zh-CN.md",
            PROJECT_ROOT / "docs" / "sragent" / "REPOSITORY_MAP.md",
            PROJECT_ROOT / "docs" / "sragent" / "REPOSITORY_MAP.zh-CN.md",
            PROJECT_ROOT / "experiments" / "README.md",
            PROJECT_ROOT / "experiments" / "README.zh-CN.md",
            PROJECT_ROOT
            / "experiments"
            / "hamilton_vs_pysr_governed_search"
            / "README.md",
            PROJECT_ROOT
            / "experiments"
            / "hamilton_vs_pysr_governed_search"
            / "README.zh-CN.md",
            PROJECT_ROOT
            / "experiments"
            / "hamilton_vs_pysr_governed_search"
            / "PROTOCOL.zh-CN.md",
            PROJECT_ROOT
            / "experiments"
            / "hamilton_vs_pysr_governed_search"
            / "DATASETS.zh-CN.md",
        ]
        errors: list[str] = []
        for document in documents:
            self.assertTrue(document.is_file(), f"missing navigation document: {document}")
            text = document.read_text(encoding="utf-8")
            for raw_target in LOCAL_LINK.findall(text):
                target = raw_target.strip().split()[0].strip("<>")
                if not target or target.startswith("#") or "://" in target:
                    continue
                relative = unquote(target.split("#", 1)[0])
                if relative and not (document.parent / relative).resolve().exists():
                    errors.append(f"{document.relative_to(PROJECT_ROOT)} -> {target}")
        self.assertEqual(errors, [], "broken repository navigation links")

    def test_hamilton_entry_and_prompt_ownership_are_unambiguous(self) -> None:
        config_dir = PROJECT_ROOT / "configs" / "hamilton"
        self.assertTrue((config_dir / "config.yaml").is_file())
        self.assertTrue((config_dir / "config_no_pysr.yaml").is_file())
        self.assertFalse((config_dir / "prompts").exists())
        prompt_dir = PROJECT_ROOT / "playground" / "hamilton" / "prompts"
        self.assertTrue(prompt_dir.is_dir())
        self.assertGreater(len(list(prompt_dir.glob("*.txt"))), 0)

    def test_generated_experiment_directories_are_ignored_by_local_policy(self) -> None:
        ignore_file = (
            PROJECT_ROOT
            / "experiments"
            / "hamilton_vs_pysr_governed_search"
            / ".gitignore"
        )
        entries = {
            line.strip()
            for line in ignore_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertTrue(
            {"data_cache/", "prepared_data/", "launch_bundle/"} <= entries
        )
        root_ignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("runs/", root_ignore)
        self.assertIn("playground/hamilton/benchmarks/*/private/", root_ignore)


if __name__ == "__main__":
    unittest.main()
