from shared.decision_policy import (
    ACTION_AVOID,
    ACTION_BUY,
    ACTION_REVIEW,
    ACTION_WATCH,
    DecisionPolicyInput,
    action_display_parts,
    derive_action_label,
    derive_action_label_from_row,
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


def test_proxy_max_not_expected_finish_is_the_actionable_gate() -> None:
    assert derive_action_label(_policy_input(bid_status="Near ceiling")) == ACTION_BUY
    assert derive_action_label(_policy_input(bid_status="At ceiling")) == ACTION_BUY
    assert derive_action_label(_policy_input(computed_verdict="Marginal (repairs)")) == ACTION_BUY
    assert derive_action_label(_policy_input(expected_auction_worst_profit=500.0)) == ACTION_BUY
    assert derive_action_label(_policy_input(expected_auction_worst_profit=-500.0)) == ACTION_BUY


def test_avoid_is_reserved_for_no_buy_states() -> None:
    assert derive_action_label(_policy_input(computed_verdict="Avoid")) == ACTION_AVOID
    assert derive_action_label(_policy_input(computed_verdict="Avoid (unresolved repairs)")) == ACTION_AVOID
    assert derive_action_label(_policy_input(bid_status="Over max")) == ACTION_AVOID
    assert derive_action_label(_policy_input(hard_max_safety="No edge")) == ACTION_AVOID
    assert derive_action_label(_policy_input(current_worst_profit=500.0)) == ACTION_AVOID


def test_review_is_reserved_for_missing_coverage_or_unknown_verdicts() -> None:
    assert derive_action_label(_policy_input(computed_verdict="Not Covered")) == ACTION_REVIEW
    assert derive_action_label(_policy_input(computed_verdict="Review (unresolved repairs)")) == ACTION_REVIEW
    assert derive_action_label(_policy_input(computed_verdict="Unexpected")) == ACTION_REVIEW


def test_action_display_copy_is_short_and_bid_specific() -> None:
    assert action_display_parts(ACTION_BUY) == (
        "Buy",
        "Set the auction-site proxy max: current worst profit and the safety ceiling clear.",
    )
    assert action_display_parts(ACTION_WATCH) == (
        "Review",
        "Review: missing or incomplete valuation context.",
    )


def test_row_action_resolver_prefers_typed_policy_fields() -> None:
    row = {
        "action_label": "Avoid",
        "computed_verdict": "Conditional Flip",
        "bid_status": "Cheap",
        "expected_auction_worst_profit": "$0",
        "expected_auction_worst_profit_value": 2500.0,
        "profit_at_current_bid_worst": "$0",
        "profit_at_current_bid_worst_value": 2400.0,
        "hard_max_safety": "Conditional",
    }

    assert derive_action_label_from_row(row, min_profit=1500.0, fallback="Avoid") == ACTION_BUY


def test_row_action_resolver_falls_back_when_policy_inputs_are_missing() -> None:
    assert derive_action_label_from_row({"action_label": "Watch"}, min_profit=1500.0, fallback="Watch") == ACTION_REVIEW
