#!/usr/bin/env python3
"""Gracefully close a persistent PySR warm-start worker."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import run_experiment as runner


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    workspace = Path.cwd().resolve()
    config_path = runner.resolve_inside(workspace, args.config, "config")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    result = runner.close_warm_start_worker(config, workspace)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
