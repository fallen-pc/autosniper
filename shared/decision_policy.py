"""Shared decision labels for live and replayed valuation surfaces."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping


ACTION_BUY = "Buy"
ACTION_WATCH = "Watch"
ACTION_AVOID = "Avoid"
ACTION_REVIEW = "Review"

NO_BUY_VERDICTS = {"Avoid", "Trap", "Not Viable"}
REVIEW_VERDICTS = {"Not Covered", "Not Eligible"}
BUYABLE_VERDICTS = {"Strong Flip", "Conditional Flip", "Good"}
WATCHABLE_VERDICTS = BUYABLE_VERDICTS | {"Marginal (repairs)"}
ACTIONABLE_BID_STATUSES = {"Cheap", "Below expected", "Open"}
NO_BUY_BID_STATUSES = {"Over max"}
ACTIONABLE_HARD_MAX_SAFETY = {"Strong", "Conditional"}

ACTION_DISPLAY_COPY = {
    ACTION_BUY: (
        ACTION_BUY,
        "Bid-ready: profit, bid room, and safety clear.",
    ),
    ACTION_WATCH: (
        ACTION_WATCH,
        "Watch: viable, but needs price room, repair inspection, or more context.",
    ),
    ACTION_AVOID: (
        ACTION_AVOID,
        "No bid: price, policy, or safety blocks it.",
    ),
    ACTION_REVIEW: (
        ACTION_REVIEW,
        "Review: missing or incomplete valuation context.",
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


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"", "nan", "none", "n/a"}:
        return ""
    return text


def first_numeric_value(*values: Any) -> float | None:
    """Return the first usable numeric/currency value from a row-like source."""

    for value in values:
        if value is None:
            continue
        if isinstance(value, (int, float)):
            try:
                if value != value:
                    continue
            except TypeError:
                pass
            return float(value)
        text = str(value).strip()
        if not text or text.lower() in {"nan", "none", "n/a"}:
            continue
        cleaned = text.replace("$", "").replace(",", "").replace("AUD", "")
        numbers = re.findall(r"-?\d+(?:\.\d+)?", cleaned)
        if not numbers:
            continue
        try:
            return float(numbers[0])
        except ValueError:
            continue
    return None


def derive_action_label_from_row(
    row: Mapping[str, Any],
    *,
    min_profit: float,
    fallback: str = ACTION_REVIEW,
) -> str:
    """Resolve a stored/display row through the shared action policy.

    This is the common boundary for AI Analysis, Missed Opportunities replay,
    and Telegram alerting. If the row lacks the policy inputs needed to safely
    recalculate the action, return the supplied fallback.
    """

    computed_verdict = _clean_text(row.get("computed_verdict") or row.get("verdict"))
    bid_status = _clean_text(row.get("bid_status"))
    hard_max_safety = _clean_text(row.get("hard_max_safety"))
    if not computed_verdict or not bid_status or not hard_max_safety:
        return _clean_text(fallback) or ACTION_REVIEW

    expected_profit = first_numeric_value(
        row.get("expected_auction_worst_profit_value"),
        row.get("expected_auction_worst_profit_value_ai"),
        row.get("expected_auction_worst_profit"),
        row.get("expected_auction_worst_profit_ai"),
        row.get("projected_profit_at_sold"),
    )
    current_profit = first_numeric_value(
        row.get("profit_at_current_bid_worst_value"),
        row.get("profit_at_current_bid_worst_value_ai"),
        row.get("profit_at_current_bid_worst"),
        row.get("profit_at_current_bid_worst_ai"),
        row.get("current_worst_profit"),
        row.get("projected_profit_at_sold"),
    )

    return derive_action_label(
        DecisionPolicyInput(
            computed_verdict=computed_verdict,
            bid_status=bid_status,
            expected_auction_worst_profit=expected_profit,
            current_worst_profit=current_profit,
            hard_max_safety=hard_max_safety,
            min_profit=min_profit,
        )
    )


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
