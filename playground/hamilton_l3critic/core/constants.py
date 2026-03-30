"""Hamilton L3/Critic constants."""

CURRENT_BEST_BEGIN = "<!-- EVO_CURRENT_BEST_BEGIN -->"
CURRENT_BEST_END = "<!-- EVO_CURRENT_BEST_END -->"
STRATEGY_QUEUE_BEGIN = "<!-- EVO_STRATEGY_QUEUE_BEGIN -->"
STRATEGY_QUEUE_END = "<!-- EVO_STRATEGY_QUEUE_END -->"

ROLE_HAMILTON = "hamilton"
ROLE_CRITIC = "critic"
ROLE_SHARED = "shared"

L3_CONTEXT_MD = "l3_context.md"
L3_CONTEXT_JSON = "l3_context.json"
L3_PROMOTION_SUMMARY = "l3_promotion_summary.json"

PROPOSAL_MD = "proposal.md"
PROPOSAL_JSON = "proposal.json"
CRITIC_REPORT_MD = "critic_report.md"
CRITIC_REPORT_JSON = "critic_report.json"
CRITIC_L3_CONTEXT_MD = "critic_l3_context.md"
CRITIC_L3_CONTEXT_JSON = "critic_l3_context.json"
REPAIR_MD = "repair_or_rebuttal.md"
REPAIR_JSON = "repair_or_rebuttal.json"
GATE_JSON = "gate_result.json"

SEVERITY_ORDER = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
}

CARD_TYPES = {
    "workflow",
    "concept",
    "failure_pattern",
    "validation_recipe",
}
