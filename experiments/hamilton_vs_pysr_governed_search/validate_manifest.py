"""Offline safety and consistency checks for the governed-search pilot manifest."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml


EXPECTED_ARMS = {
    "ordinary_pysr",
    "fixed_schedule_pysr",
    "governed_hamilton",
}
REQUIRED_FAIRNESS_FIELDS = {
    "public_dataset_bytes",
    "data_fingerprint",
    "train_validation_split",
    "feature_and_target_columns",
    "initial_pysr_search_space",
    "cumulative_pysr_evaluations",
    "candidate_evaluator",
    "scientific_gates",
    "paired_seed_plan",
    "code_and_environment",
}
FORBIDDEN_PATH_MARKERS = (
    "/private/",
    "\\private\\",
    "_test.csv",
    "_ood",
    "below_lockin",
    "above_lockin",
    "free_vibration",
)


class ManifestError(ValueError):
    """Raised when a preregistration manifest violates its contract."""


def _require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def _string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for child in value for item in _string_values(child)]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _string_values(child)]
    return []


def load_manifest(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ManifestError("manifest root must be an object")
    return payload


def validate_manifest(payload: dict[str, Any], mode: str = "preparation") -> list[str]:
    if mode not in {"preparation", "launch"}:
        raise ValueError(f"unknown validation mode: {mode}")

    errors: list[str] = []
    _require(payload.get("schema_version") == 1, "schema_version must be 1", errors)
    _require(bool(payload.get("experiment_id")), "experiment_id is required", errors)

    permissions = payload.get("permissions")
    _require(isinstance(permissions, dict), "permissions must be an object", errors)
    if isinstance(permissions, dict):
        expected_permissions = (
            {"deepseek": False, "pysr_julia": False, "private_ood": False}
            if mode == "preparation"
            else {"deepseek": True, "pysr_julia": True, "private_ood": False}
        )
        for permission, expected in expected_permissions.items():
            _require(
                permissions.get(permission) is expected,
                f"{mode} permission {permission} must be {str(expected).lower()}",
                errors,
            )

    arms = payload.get("arms")
    _require(isinstance(arms, list), "arms must be a list", errors)
    arm_ids: set[str] = set()
    if isinstance(arms, list):
        for index, arm in enumerate(arms):
            if not isinstance(arm, dict) or not isinstance(arm.get("id"), str):
                errors.append(f"arms[{index}] must contain a string id")
                continue
            arm_ids.add(arm["id"])
        _require(arm_ids == EXPECTED_ARMS, "the three preregistered arms must be present", errors)
        _require(len(arm_ids) == len(arms), "arm ids must be unique", errors)

    fairness = payload.get("fairness")
    _require(isinstance(fairness, dict), "fairness must be an object", errors)
    episode_count = None
    if isinstance(fairness, dict):
        locked = fairness.get("locked_fields")
        _require(isinstance(locked, list), "fairness.locked_fields must be a list", errors)
        if isinstance(locked, list):
            missing = REQUIRED_FAIRNESS_FIELDS - set(locked)
            _require(not missing, f"missing fairness fields: {sorted(missing)}", errors)
        episode_count = fairness.get("episode_count")
        _require(
            isinstance(episode_count, int) and not isinstance(episode_count, bool)
            and episode_count > 0,
            "fairness.episode_count must be a positive integer",
            errors,
        )
        _require(
            fairness.get("fixed_schedule_matches_hamilton_allowances") is True,
            "fixed schedule must match Hamilton episode allowances",
            errors,
        )

    repeats = (payload.get("seed_plan") or {}).get("repeats")
    _require(isinstance(repeats, list) and bool(repeats), "paired seed repeats are required", errors)
    repeat_ids: set[str] = set()
    if isinstance(repeats, list):
        for index, repeat in enumerate(repeats):
            if not isinstance(repeat, dict):
                errors.append(f"seed_plan.repeats[{index}] must be an object")
                continue
            repeat_id = repeat.get("repeat_id")
            _require(
                isinstance(repeat_id, str) and bool(repeat_id),
                f"seed_plan.repeats[{index}].repeat_id is required",
                errors,
            )
            if isinstance(repeat_id, str):
                repeat_ids.add(repeat_id)
            seeds = repeat.get("episode_seeds")
            _require(
                isinstance(seeds, list)
                and episode_count is not None
                and len(seeds) == episode_count
                and all(isinstance(seed, int) and not isinstance(seed, bool) for seed in seeds),
                f"seed_plan.repeats[{index}] must have {episode_count} integer episode seeds",
                errors,
            )
            if isinstance(seeds, list) and seeds:
                _require(
                    repeat.get("ordinary_primary_seed") == seeds[0],
                    f"seed_plan.repeats[{index}] primary seed must equal first episode seed",
                    errors,
                )
        _require(len(repeat_ids) == len(repeats), "repeat ids must be unique", errors)

    families = payload.get("dataset_families")
    _require(isinstance(families, list) and bool(families), "dataset families are required", errors)
    family_ids: set[str] = set()
    total_tasks = 0
    if isinstance(families, list):
        for index, family in enumerate(families):
            if not isinstance(family, dict):
                errors.append(f"dataset_families[{index}] must be an object")
                continue
            family_id = family.get("id")
            if isinstance(family_id, str):
                family_ids.add(family_id)
            _require(
                family.get("public_only") is True,
                f"dataset family {family_id or index} must be public-only",
                errors,
            )
            _require(
                family.get("ground_truth_agent_visible") is False,
                f"dataset family {family_id or index} must hide ground truth from the Agent",
                errors,
            )
            task_count = family.get("task_count")
            _require(
                isinstance(task_count, int) and not isinstance(task_count, bool) and task_count > 0,
                f"dataset family {family_id or index} needs a positive task_count",
                errors,
            )
            if isinstance(task_count, int) and not isinstance(task_count, bool):
                total_tasks += task_count
            if mode == "launch":
                _require(
                    family.get("status") == "frozen",
                    f"launch dataset family {family_id or index} must be frozen",
                    errors,
                )
                tasks = family.get("tasks")
                _require(
                    isinstance(tasks, list) and len(tasks) == task_count,
                    f"launch dataset family {family_id or index} must list every task",
                    errors,
                )
                if isinstance(tasks, list):
                    for task_index, task in enumerate(tasks):
                        task_label = f"{family_id or index}.tasks[{task_index}]"
                        _require(
                            isinstance(task, dict),
                            f"launch dataset {task_label} must be an object",
                            errors,
                        )
                        if not isinstance(task, dict):
                            continue
                        for field in ("id", "input", "source_revision", "sha256"):
                            _require(
                                isinstance(task.get(field), str) and bool(task.get(field)),
                                f"launch dataset {task_label}.{field} is required",
                                errors,
                            )
                        fingerprint = task.get("sha256")
                        _require(
                            isinstance(fingerprint, str)
                            and len(fingerprint) == 64
                            and all(character in "0123456789abcdef" for character in fingerprint),
                            f"launch dataset {task_label}.sha256 must be lowercase SHA-256",
                            errors,
                        )
        _require(len(family_ids) == len(families), "dataset family ids must be unique", errors)
        _require(
            family_ids
            == {"blind_static_known_truth", "known_dynamics_derivatives", "viv_public"},
            "pilot must contain the three preregistered dataset families",
            errors,
        )
        _require(total_tasks == 11, "pilot must contain exactly eleven planned tasks", errors)

    dataset_text = "\n".join(_string_values(families)).lower()
    for marker in FORBIDDEN_PATH_MARKERS:
        _require(marker not in dataset_text, f"private/OOD marker is forbidden: {marker}", errors)

    outcomes = payload.get("outcomes") or {}
    common_primary = outcomes.get("common_primary") if isinstance(outcomes, dict) else None
    _require(
        isinstance(common_primary, list)
        and {
            "terminal_public_validation_nrmse",
            "anytime_best_validation_auc",
            "structured_run_success",
        }.issubset(set(common_primary)),
        "common primary outcomes are incomplete",
        errors,
    )

    budget = payload.get("budget")
    _require(isinstance(budget, dict), "budget must be an object", errors)
    if isinstance(budget, dict):
        if mode == "preparation":
            _require(
                budget.get("authorization_state")
                == "frozen_pending_user_authorization",
                "preparation budget must be frozen pending user authorization",
                errors,
            )
            total = budget.get("max_total_evals_per_task")
            episode_evals = budget.get("episode_evals")
            _require(
                isinstance(total, int) and not isinstance(total, bool) and total > 0,
                "preparation requires a positive proposed cumulative budget",
                errors,
            )
            _require(
                episode_evals == "realized_from_paired_hamilton_ledger",
                "preparation requires Hamilton-realized paired episode allowances",
                errors,
            )
            bounds = budget.get("hamilton_dynamic_bounds")
            _require(
                isinstance(bounds, dict)
                and all(
                    isinstance(bounds.get(name), int)
                    and not isinstance(bounds.get(name), bool)
                    and bounds[name] > 0
                    for name in ("base_evals", "min_evals", "max_evals", "rounding_quantum")
                )
                and bounds["min_evals"] <= bounds["base_evals"] <= bounds["max_evals"],
                "preparation requires valid Hamilton dynamic-budget bounds",
                errors,
            )
            _require(
                budget.get("allocation_policy")
                == "hamilton_dynamic_then_paired_pysr_replay",
                "preparation requires Hamilton-first paired budget replay",
                errors,
            )
        else:
            total = budget.get("max_total_evals_per_task")
            episode_evals = budget.get("episode_evals")
            _require(
                budget.get("authorization_state") == "authorized",
                "launch requires explicit evaluation-budget authorization",
                errors,
            )
            _require(
                isinstance(total, int) and not isinstance(total, bool) and total > 0,
                "launch requires a positive cumulative evaluation budget",
                errors,
            )
            _require(
                episode_evals == "realized_from_paired_hamilton_ledger",
                "launch requires Hamilton-realized paired episode allowances",
                errors,
            )

    if mode == "preparation":
        _require(
            payload.get("status") == "configured_waiting_authorization",
            "preparation manifest status must be configured_waiting_authorization",
            errors,
        )
        _require(payload.get("launch_blocked") is True, "preparation must block launch", errors)
        blockers = payload.get("readiness_blockers")
        _require(isinstance(blockers, list) and bool(blockers), "readiness blockers are required", errors)
    else:
        _require(payload.get("status") == "frozen", "launch manifest status must be frozen", errors)
        _require(payload.get("launch_blocked") is False, "launch manifest must explicitly unblock launch", errors)
        _require(not payload.get("readiness_blockers"), "launch manifest cannot retain blockers", errors)

    return errors


def validate_path(path: Path, mode: str = "preparation") -> None:
    errors = validate_manifest(load_manifest(path), mode=mode)
    if errors:
        raise ManifestError("\n".join(f"- {error}" for error in errors))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--mode", choices=("preparation", "launch"), default="preparation")
    args = parser.parse_args()
    try:
        validate_path(args.manifest, mode=args.mode)
    except ManifestError as exc:
        print(f"manifest validation failed ({args.mode}):\n{exc}")
        return 1
    print(f"manifest validation passed ({args.mode}): {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
