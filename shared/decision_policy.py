"""Shared decision labels for live and replayed valuation surfaces."""

from __future__ import annotations

from dataclasses import dataclass


ACTION_BUY = "Buy"
ACTION_WATCH = "Watch"
ACTION_AVOID = "Avoid"
ACTION_REVIEW = "Review"

NO_BUY_VERDICTS = {"Avoid", "Trap", "Not Viable"}
REVIEW_VERDICTS = {"Not Covered", "Not Eligible"}
BUYABLE_VERDICTS = {"Strong Flip", "Conditional Flip", "Good"}
WATCHABLE_VERDICTS = BUYABLE_VERDICTS | {"Marginal (repairs)"}
ACTIONABLE_BID_STATUSES = {"Cheap", "Below expected", "Open"}
NO_BUY_BID_STATUSES = {"Over max", "At ceiling"}
ACTIONABLE_HARD_MAX_SAFETY = {"Strong", "Conditional"}

ACTION_DISPLAY_COPY = {
    ACTION_BUY: (
        ACTION_BUY,
        "Bid-ready: profit, bid room, and max-bid safety all clear.",
    ),
    ACTION_WATCH: (
        ACTION_WATCH,
        "Watch only: positive signal, but not bid-ready yet.",
    ),
    ACTION_AVOID: (
        ACTION_AVOID,
        "No bid: fails profit, bid status, or safety.",
    ),
    ACTION_REVIEW: (
        ACTION_REVIEW,
        "Manual check: missing or incomplete valuation context.",
    ),
}


@dataclass(frozen=True)
class DecisionPolicyInput:
    computed_verdict: str
    bid_status: str
    expected_auction_worst_profit: float | None
    current_worst_profit: float | None
    hard_max_safety: str
    min_profit: float


def derive_action_label(policy_input: DecisionPolicyInput) -> str:
    """Return the operator action label used across buying surfaces.

    Buy means the listing is currently actionable: it has safe coverage, positive
    current and expected-finish worst-case profit, bid room, and hard-max safety.
    Watch means the listing is not a hard no, but needs time, price movement, or
    manual inspection before bidding. Avoid means do not bid. Review is reserved
    for missing coverage or incomplete valuation context.
    """

    verdict = (policy_input.computed_verdict or "").strip()
    bid_status = (policy_input.bid_status or "").strip()
    hard_max_safety = (policy_input.hard_max_safety or "").strip()
    expected_profit = policy_input.expected_auction_worst_profit
    current_profit = policy_input.current_worst_profit
    min_profit = float(policy_input.min_profit or 0.0)

    if verdict in NO_BUY_VERDICTS:
        return ACTION_AVOID
    if verdict in REVIEW_VERDICTS:
        return ACTION_REVIEW
    if bid_status in NO_BUY_BID_STATUSES or hard_max_safety == "No edge":
        return ACTION_AVOID
    if verdict not in WATCHABLE_VERDICTS:
        return ACTION_REVIEW

    current_viable = current_profit is not None and current_profit >= min_profit
    expected_viable = expected_profit is not None and expected_profit >= min_profit
    max_safe = hard_max_safety in ACTIONABLE_HARD_MAX_SAFETY
    bid_actionable = bid_status in ACTIONABLE_BID_STATUSES

    if (
        verdict in BUYABLE_VERDICTS
        and current_viable
        and expected_viable
        and max_safe
        and bid_actionable
    ):
        return ACTION_BUY
    return ACTION_WATCH


def action_display_parts(action: object) -> tuple[str, str]:
    """Return the operator-facing label and explanation for an action value."""

    action_text = str(action or "").strip()
    if not action_text or action_text.lower() in {"nan", "none", "n/a"}:
        action_text = ACTION_REVIEW
    return ACTION_DISPLAY_COPY.get(
        action_text,
        (
            action_text,
            "Manual check: action is not one of the standard policy labels.",
        ),
    )
