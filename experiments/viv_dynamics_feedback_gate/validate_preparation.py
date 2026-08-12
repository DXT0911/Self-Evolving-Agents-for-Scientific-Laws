#!/usr/bin/env python3
"""Validate the preparation-only VIV dynamics-feedback gate without running it."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEFAULT_MANIFEST = HERE / "preparation_manifest.yaml"
DEFAULT_SPECS = HERE / "arm_specs.yaml"
EXPECTED_ARMS = {"direct_pysr", "fit_only_hamilton", "dynamics_aware_hamilton"}
FORBIDDEN_TEXT = (
    "/private/",
    "\\private\\",
    "_test.csv",
    "/ood/",
    "\\ood\\",
    "_ood.csv",
    "below_lockin",
    "above_lockin",
    "free_vibration",
)


class GateValidationError(ValueError):
    """Raised when the preparation gate violates a frozen contract."""


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise GateValidationError(f"{path.name} must contain an object")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def validate(
    manifest: dict[str, Any],
    specs: dict[str, Any],
    *,
    mode: str = "preparation",
) -> list[str]:
    if mode not in {"preparation", "authorized", "launch"}:
        raise ValueError(f"unknown mode: {mode}")
    errors: list[str] = []
    require(manifest.get("schema_version") == 1, "manifest schema_version must be 1", errors)
    experiment_id = manifest.get("experiment_id")
    require(bool(experiment_id), "manifest experiment_id is required", errors)
    require(specs.get("experiment_id") == experiment_id, "experiment ids must match", errors)

    permissions = manifest.get("permissions", {})
    if mode == "preparation":
        require(manifest.get("status") == "configured_waiting_authorization", "preparation status is invalid", errors)
        require(manifest.get("launch_blocked") is True, "preparation must block launch", errors)
        require(manifest.get("execution_permitted") is False, "preparation cannot permit execution", errors)
        for name in ("deepseek", "pysr_julia", "private_ood"):
            require(permissions.get(name) is False, f"preparation permission {name} must be false", errors)
        require(bool(manifest.get("readiness_blockers")), "preparation blockers are required", errors)
        require(specs.get("executable_configs_materialized") is False, "preparation cannot contain executable configs", errors)
    elif mode == "authorized":
        require(manifest.get("status") == "authorized_waiting_environment", "authorized status is invalid", errors)
        require(manifest.get("launch_blocked") is True, "environment blocker must keep launch blocked", errors)
        require(manifest.get("execution_permitted") is False, "blocked environment cannot permit execution", errors)
        require(permissions.get("deepseek") is True, "DeepSeek authorization must be recorded", errors)
        require(permissions.get("pysr_julia") is True, "PySR/Julia authorization must be recorded", errors)
        require(permissions.get("private_ood") is False, "private/OOD must remain forbidden", errors)
        require(bool(manifest.get("readiness_blockers")), "environment blockers are required", errors)
        require(specs.get("executable_configs_materialized") is False, "blocked state cannot claim materialized configs", errors)
    else:
        require(manifest.get("status") == "frozen_authorized", "launch status must be frozen_authorized", errors)
        require(manifest.get("launch_blocked") is False, "launch must be explicitly unblocked", errors)
        require(manifest.get("execution_permitted") is True, "launch must explicitly permit execution", errors)
        require(permissions.get("deepseek") is True, "launch needs DeepSeek authorization", errors)
        require(permissions.get("pysr_julia") is True, "launch needs PySR/Julia authorization", errors)
        require(permissions.get("private_ood") is False, "private/OOD must remain forbidden", errors)
        require(not manifest.get("readiness_blockers"), "launch cannot retain blockers", errors)
        require(specs.get("executable_configs_materialized") is True, "launch needs executable configs", errors)

    require(manifest.get("private_ood_permitted") is False, "private/OOD permission must be false", errors)
    scope = manifest.get("scope", {})
    require(scope.get("public_only") is True, "scope must be public-only", errors)
    require(scope.get("task_ids") == ["viv_u248"], "scope must contain only viv_u248", errors)
    require(scope.get("repeats") == ["repeat_1"], "scope must contain one frozen repeat", errors)
    require(set(scope.get("arm_ids", [])) == EXPECTED_ARMS, "scope must contain the three arms", errors)
    require(scope.get("total_arm_runs") == 3, "scope must contain exactly three arm runs", errors)

    public_data = manifest.get("public_data", {})
    input_path = ROOT / str(public_data.get("input", ""))
    require(input_path.is_file(), "public input is missing", errors)
    if input_path.is_file():
        require(sha256(input_path) == public_data.get("sha256"), "public input SHA-256 mismatch", errors)
    require(public_data.get("feature_columns") == ["x", "v"], "features must be x and v", errors)
    require(public_data.get("target_column") == "a", "target must be a", errors)
    require(public_data.get("time_column") == "t", "time column must be t", errors)

    frozen_inputs = manifest.get("frozen_inputs", {})
    require(
        set(frozen_inputs) == {"protocol", "arm_specs", "calibration_report", "verifier_source"},
        "frozen inputs must contain exactly the protocol, arm specs, calibration report, and verifier source",
        errors,
    )
    for name, record in frozen_inputs.items():
        require(isinstance(record, dict), f"frozen input {name} must be an object", errors)
        if not isinstance(record, dict):
            continue
        frozen_path = ROOT / str(record.get("path", ""))
        require(frozen_path.is_file(), f"frozen input {name} is missing", errors)
        if frozen_path.is_file():
            require(sha256(frozen_path) == record.get("sha256"), f"frozen input {name} SHA-256 mismatch", errors)

    seed_plan = manifest.get("seed_plan", {})
    seeds = seed_plan.get("hamilton_round_seeds")
    require(
        isinstance(seeds, list) and len(seeds) == 3 and len(set(seeds)) == 3
        and all(isinstance(seed, int) and not isinstance(seed, bool) for seed in seeds),
        "three unique integer Hamilton round seeds are required",
        errors,
    )
    if isinstance(seeds, list) and seeds:
        require(seed_plan.get("primary_seed") == seeds[0], "primary seed must equal first round seed", errors)

    evaluation = manifest.get("requested_evaluation_budget", {})
    expected_budget_state = "frozen_pending_user_authorization" if mode == "preparation" else "authorized"
    require(evaluation.get("authorization_state") == expected_budget_state, "evaluation authorization state mismatch", errors)
    require(evaluation.get("maximum_per_arm") == 12000, "per-arm ceiling must be 12000", errors)
    require(evaluation.get("maximum_all_arms") == 36000, "total ceiling must be 36000", errors)
    require(evaluation.get("hamilton_round_count") == 3, "Hamilton must use three rounds", errors)
    bounds = evaluation.get("hamilton_dynamic_bounds", {})
    require(bounds == {"base_evals": 4000, "min_evals": 2000, "max_evals": 6000, "rounding_quantum": 500}, "dynamic bounds differ from frozen values", errors)

    tokens = manifest.get("proposed_llm_token_budget", {})
    require(tokens.get("authorization_state") == expected_budget_state, "LLM token authorization state mismatch", errors)
    require(tokens.get("maximum_per_hamilton_arm") == 600000, "Hamilton token ceiling must be 600000 per arm", errors)
    require(tokens.get("maximum_all_hamilton_arms") == 1200000, "total token ceiling must be 1200000", errors)
    require(tokens.get("direct_pysr_tokens") == 0, "direct PySR cannot consume LLM tokens", errors)

    arms = specs.get("arms", {})
    require(set(arms) == EXPECTED_ARMS, "arm specs must contain exactly the three arms", errors)
    if set(arms) == EXPECTED_ARMS:
        direct = arms["direct_pysr"]
        fit = arms["fit_only_hamilton"]
        dynamics = arms["dynamics_aware_hamilton"]
        require(direct.get("llm_enabled") is False, "direct PySR must not use an LLM", errors)
        require(direct.get("requested_evaluations") == 12000, "direct PySR budget mismatch", errors)
        for arm_id, arm in (("fit-only", fit), ("dynamics-aware", dynamics)):
            require(arm.get("llm_enabled") is True, f"{arm_id} Hamilton must use an LLM", errors)
            require(arm.get("cumulative_requested_evaluations") == 12000, f"{arm_id} budget mismatch", errors)
            require(arm.get("round_seeds") == seeds, f"{arm_id} seeds mismatch", errors)
        fit_weights = fit.get("search_time_ranking_weights", {})
        dynamics_weights = dynamics.get("search_time_ranking_weights", {})
        require(fit_weights.get("trajectory_nrmse") == 0.0, "fit-only trajectory weight must be zero", errors)
        require(fit_weights.get("long_horizon_penalty") == 0.0, "fit-only long-horizon weight must be zero", errors)
        require(dynamics_weights.get("trajectory_nrmse") == 1.0, "dynamics-aware trajectory weight must be one", errors)
        require(dynamics_weights.get("long_horizon_penalty") == 1.0, "dynamics-aware long-horizon weight must be one", errors)
        withheld = set(fit.get("evidence_withheld_until_endpoint_freeze", []))
        require({"short_ode_trajectory", "long_horizon_dynamics"}.issubset(withheld), "fit-only dynamics evidence must be withheld", errors)
        released = set(dynamics.get("evidence_released_to_llm", []))
        require("long_horizon_controller_summary" in released, "dynamics-aware summary must be released", errors)

    final = specs.get("common_final_evaluator", {}).get("long_horizon_dynamics", {})
    expected_final = {
        "duration": 60.0,
        "points": 3000,
        "steady_state_fraction": 0.4,
        "min_steady_cycles": 3.0,
        "zero_initial_policy": "report_only",
        "amplitude_relative_tolerance": 0.20,
        "frequency_relative_tolerance": 0.10,
        "stationarity_relative_tolerance": 0.15,
        "attractor_relative_tolerance": 0.20,
    }
    for key, value in expected_final.items():
        require(final.get(key) == value, f"long-horizon {key} differs from frozen value", errors)

    serialized = yaml.safe_dump({"manifest": manifest, "specs": specs}).lower()
    for marker in FORBIDDEN_TEXT:
        require(marker not in serialized, f"forbidden private/OOD marker present: {marker}", errors)
    return errors


def validate_paths(
    manifest_path: Path = DEFAULT_MANIFEST,
    specs_path: Path = DEFAULT_SPECS,
    *,
    mode: str = "preparation",
) -> None:
    errors = validate(load_yaml(manifest_path), load_yaml(specs_path), mode=mode)
    if errors:
        raise GateValidationError("\n".join(f"- {error}" for error in errors))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--specs", type=Path, default=DEFAULT_SPECS)
    parser.add_argument("--mode", choices=("preparation", "authorized", "launch"), default="preparation")
    args = parser.parse_args()
    try:
        validate_paths(args.manifest, args.specs, mode=args.mode)
    except GateValidationError as exc:
        print(f"VIV dynamics-feedback gate validation failed ({args.mode}):\n{exc}")
        return 1
    print(f"VIV dynamics-feedback gate validation passed ({args.mode})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
