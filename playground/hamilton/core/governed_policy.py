"""Deterministic policy primitives for governed symbolic-regression search.

The LLM may propose a falsifiable structural hypothesis, but it does not choose
which candidate survives or unilaterally change a live PySR session.  This
module turns compact numerical diagnostics into an auditable controller action.
It is deliberately independent from PySR and model providers so policies can be
replayed offline on frozen result JSON files.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable


ALLOWED_ACTIONS = {"continue", "modify", "branch", "rollback", "stop"}
ALLOWED_PLAN_KEYS = {
    "hypothesis",
    "candidate_variables",
    "candidate_operators",
    "requested_action",
    "falsification",
}


@dataclass(frozen=True)
class PolicyThresholds:
    min_score_improvement: float = 1e-4
    stale_rounds_before_intervention: int = 2
    high_complexity_fraction: float = 0.80
    low_complexity_fraction: float = 0.25
    material_residual_correlation: float = 0.30
    min_validation_nrmse_for_residual_intervention: float = 0.02
    parsimony_multiplier: float = 2.0
    min_parsimony: float = 1e-8
    max_parsimony: float = 1.0


def _finite_float(value: object, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number == number and abs(number) != float("inf") else default


def _correlation_value(record: object) -> float:
    if not isinstance(record, dict):
        return 0.0
    return abs(_finite_float(record.get("value")))


def diagnostic_snapshot(
    result: dict[str, Any],
    *,
    incumbent_score_before: float | None,
    stale_rounds_before: int,
    rollback_required: bool = False,
) -> dict[str, Any]:
    """Project a result onto the small set of signals used by the policy."""
    selected = result.get("selected") if isinstance(result.get("selected"), dict) else {}
    config = result.get("config") if isinstance(result.get("config"), dict) else {}
    search = config.get("search") if isinstance(config.get("search"), dict) else {}
    verification = (
        result.get("verification")
        if isinstance(result.get("verification"), dict)
        else {}
    )
    residual = verification.get("residual_diagnostics")
    residual = residual if isinstance(residual, dict) else {}
    validation = residual.get("validation")
    validation = validation if isinstance(validation, dict) else {}
    state = validation.get("state_dependence")
    state = state if isinstance(state, dict) else {}
    temporal = validation.get("temporal_structure")
    temporal = temporal if isinstance(temporal, dict) else {}

    score = _finite_float(selected.get("scientific_score"), float("inf"))
    selected_equation = selected.get("simplified_equation")
    validation_nrmse = 0.0
    for candidate in result.get("candidates", []):
        if (
            isinstance(candidate, dict)
            and candidate.get("simplified_equation") == selected_equation
        ):
            ranking = candidate.get("ranking")
            if isinstance(ranking, dict):
                validation_nrmse = max(
                    0.0, _finite_float(ranking.get("validation_nrmse"))
                )
            break
    prior = score if incumbent_score_before is None else float(incumbent_score_before)
    improvement = prior - score
    complexity = max(0.0, _finite_float(selected.get("complexity")))
    maxsize = max(1.0, _finite_float(search.get("maxsize"), 1.0))
    state_corr = _correlation_value(state.get("strongest_absolute_correlation"))
    temporal_corr = _correlation_value(
        temporal.get("strongest_reported_autocorrelation")
    )
    term_influence = verification.get("term_influence")
    term_influence = term_influence if isinstance(term_influence, dict) else {}
    positive_terms = [
        item
        for item in term_influence.get("terms", [])
        if isinstance(item, dict) and _finite_float(item.get("validation_nrmse_delta")) > 0
    ]
    return {
        "scientific_score": score,
        "validation_nrmse": validation_nrmse,
        "score_improvement": improvement,
        "improved": improvement > 0,
        "complexity_fraction": complexity / maxsize,
        "parsimony": max(
            0.0,
            _finite_float(search.get("parsimony"), 0.0),
        ),
        "state_residual_correlation": state_corr,
        "temporal_residual_correlation": temporal_corr,
        "material_residual_correlation": max(state_corr, temporal_corr),
        "positive_influence_terms": len(positive_terms),
        "stale_rounds_before": max(0, int(stale_rounds_before)),
        "rollback_required": bool(rollback_required),
    }


def validate_planner_proposal(
    proposal: dict[str, Any],
    *,
    allowed_variables: Iterable[str],
    allowed_operators: Iterable[str],
) -> dict[str, Any]:
    """Validate the only structure an LLM planner is allowed to author.

    The returned object is advisory evidence.  It cannot contain a score,
    equation-selection decision, arbitrary config patch, or budget request.
    """
    if not isinstance(proposal, dict):
        raise ValueError("planner proposal must be an object")
    unknown = sorted(set(proposal) - ALLOWED_PLAN_KEYS)
    if unknown:
        raise ValueError(f"planner proposal contains unauthorized fields: {unknown}")
    hypothesis = proposal.get("hypothesis")
    falsification = proposal.get("falsification")
    if not isinstance(hypothesis, str) or not hypothesis.strip():
        raise ValueError("planner proposal requires a non-empty hypothesis")
    if not isinstance(falsification, str) or not falsification.strip():
        raise ValueError("planner proposal requires a non-empty falsification")
    requested = proposal.get("requested_action", "continue")
    if requested not in ALLOWED_ACTIONS:
        raise ValueError(f"unsupported requested_action: {requested}")

    variable_allowlist = set(allowed_variables)
    operator_allowlist = set(allowed_operators)
    variables = proposal.get("candidate_variables", [])
    operators = proposal.get("candidate_operators", [])
    if not isinstance(variables, list) or not all(isinstance(v, str) for v in variables):
        raise ValueError("candidate_variables must be a string list")
    if not isinstance(operators, list) or not all(isinstance(v, str) for v in operators):
        raise ValueError("candidate_operators must be a string list")
    unauthorized_variables = sorted(set(variables) - variable_allowlist)
    unauthorized_operators = sorted(set(operators) - operator_allowlist)
    if unauthorized_variables or unauthorized_operators:
        raise ValueError(
            "planner proposal exceeds the frozen envelope: "
            f"variables={unauthorized_variables}, operators={unauthorized_operators}"
        )
    return {
        "hypothesis": hypothesis.strip(),
        "candidate_variables": sorted(set(variables)),
        "candidate_operators": sorted(set(operators)),
        "requested_action": requested,
        "falsification": falsification.strip(),
        "authority": "advisory_only",
    }


def choose_action(
    snapshot: dict[str, Any],
    *,
    thresholds: PolicyThresholds | None = None,
    warm_compatible_fields: Iterable[str] = ("search.parsimony",),
) -> dict[str, Any]:
    """Choose a deterministic action from frozen numerical diagnostics."""
    policy = thresholds or PolicyThresholds()
    warm_fields = set(warm_compatible_fields)
    improvement = _finite_float(snapshot.get("score_improvement"))
    stale = max(0, int(snapshot.get("stale_rounds_before", 0) or 0))
    complexity = _finite_float(snapshot.get("complexity_fraction"))
    residual = _finite_float(snapshot.get("material_residual_correlation"))
    residual_eligible = (
        _finite_float(snapshot.get("validation_nrmse"))
        >= policy.min_validation_nrmse_for_residual_intervention
    )
    parsimony = max(
        policy.min_parsimony,
        _finite_float(snapshot.get("parsimony"), policy.min_parsimony),
    )

    if snapshot.get("rollback_required"):
        return _decision("rollback", "trust-region rollback gate is active")
    if improvement >= policy.min_score_improvement:
        return _decision("continue", "incumbent is still improving")
    if stale + 1 < policy.stale_rounds_before_intervention:
        return _decision("continue", "insufficient evidence of sustained stagnation")

    if "search.parsimony" in warm_fields and complexity >= policy.high_complexity_fraction:
        value = min(policy.max_parsimony, parsimony * policy.parsimony_multiplier)
        return _decision(
            "modify",
            "search is stagnant and the incumbent is near the complexity ceiling",
            field="search.parsimony",
            value=value,
        )
    if (
        "search.parsimony" in warm_fields
        and complexity <= policy.low_complexity_fraction
        and residual_eligible
        and residual >= policy.material_residual_correlation
    ):
        value = max(policy.min_parsimony, parsimony / policy.parsimony_multiplier)
        return _decision(
            "modify",
            "search is stagnant, simple, and leaves material residual structure",
            field="search.parsimony",
            value=value,
        )
    if residual_eligible and residual >= policy.material_residual_correlation:
        return _decision(
            "branch",
            "material residual structure remains but no warm-safe intervention is justified",
            requires_restart=True,
        )
    return _decision(
        "continue",
        "no diagnostic justifies changing the live search configuration",
    )


def _decision(
    action: str,
    reason: str,
    *,
    field: str | None = None,
    value: Any = None,
    requires_restart: bool = False,
) -> dict[str, Any]:
    patch = {} if field is None else {field: value}
    return {
        "action": action,
        "reason": reason,
        "config_field": field,
        "config_patch": patch,
        "requires_restart": bool(requires_restart),
        "authority": "deterministic_controller",
    }


def infer_process_state(snapshot: dict[str, Any]) -> str:
    """Map diagnostics to the memory view needed by the next decision."""
    if snapshot.get("rollback_required"):
        return "rollback"
    if _finite_float(snapshot.get("score_improvement")) > 0:
        return "improving"
    if _finite_float(snapshot.get("complexity_fraction")) >= 0.80:
        return "complex_valid"
    if _finite_float(snapshot.get("material_residual_correlation")) >= 0.30:
        return "stagnant_structured"
    return "stagnant_unstructured"


def route_memory(memory: dict[str, Any], process_state: str) -> dict[str, Any]:
    """Expose only state-relevant L2 partitions to the planner."""
    routed = memory.get("routed") if isinstance(memory.get("routed"), dict) else {}
    mapping = {
        "improving": ("elite", "diagnostics"),
        "complex_valid": ("elite", "motifs", "diagnostics"),
        "stagnant_structured": ("elite", "motifs", "failures", "diagnostics"),
        "stagnant_unstructured": ("elite", "failures", "diagnostics"),
        "rollback": ("elite", "failures"),
    }
    selected = mapping.get(process_state, ("elite", "diagnostics"))
    limits = {"elite": 3, "motifs": 8, "failures": 5, "diagnostics": 4}
    return {
        "process_state": process_state,
        "partitions": {
            name: list(routed.get(name, []))[-limits[name] :]
            for name in selected
        },
    }


def policy_manifest(thresholds: PolicyThresholds | None = None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "thresholds": asdict(thresholds or PolicyThresholds()),
        "llm_authority": "advisory_structural_hypothesis_only",
        "controller_authority": [
            "action_selection",
            "config_sanitization",
            "candidate_retention",
            "rollback",
            "budget",
        ],
    }
