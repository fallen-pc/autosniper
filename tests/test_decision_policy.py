from shared.decision_policy import (
    ACTION_AVOID,
    ACTION_BUY,
    ACTION_REVIEW,
    ACTION_WATCH,
    DecisionPolicyInput,
    action_display_parts,
    derive_action_label,
)


def _policy_input(**overrides) -> DecisionPolicyInput:
    values = {
        "computed_verdict": "Conditional Flip",
        "bid_status": "Cheap",
        "expected_auction_worst_profit": 2500.0,
        "current_worst_profit": 2500.0,
        "hard_max_safety": "Conditional",
        "min_profit": 1500.0,
    }
    values.update(overrides)
    return DecisionPolicyInput(**values)


def test_buy_requires_actionable_profit_bid_room_and_safety() -> None:
    assert derive_action_label(_policy_input()) == ACTION_BUY


def test_watch_is_viable_but_not_currently_actionable() -> None:
    assert derive_action_label(_policy_input(bid_status="Near ceiling")) == ACTION_WATCH
    assert derive_action_label(_policy_input(computed_verdict="Marginal (repairs)")) == ACTION_WATCH
    assert derive_action_label(_policy_input(expected_auction_worst_profit=500.0)) == ACTION_WATCH


def test_avoid_is_reserved_for_no_buy_states() -> None:
    assert derive_action_label(_policy_input(computed_verdict="Avoid")) == ACTION_AVOID
    assert derive_action_label(_policy_input(bid_status="Over max")) == ACTION_AVOID
    assert derive_action_label(_policy_input(hard_max_safety="No edge")) == ACTION_AVOID


def test_review_is_reserved_for_missing_coverage_or_unknown_verdicts() -> None:
    assert derive_action_label(_policy_input(computed_verdict="Not Covered")) == ACTION_REVIEW
    assert derive_action_label(_policy_input(computed_verdict="Unexpected")) == ACTION_REVIEW


def test_action_display_copy_is_short_and_bid_specific() -> None:
    assert action_display_parts(ACTION_BUY) == (
        "Buy",
        "Bid-ready: profit, bid room, and safety clear.",
    )
    assert action_display_parts(ACTION_WATCH) == (
        "Watch",
        "Watch: useful economics, but not bid-ready yet.",
    )
