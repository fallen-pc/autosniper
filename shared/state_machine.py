from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

import pandas as pd

from shared.schema import (
    ALLOWED_LISTING_STATES,
    STATE_ACTIVE,
    STATE_DEAD_URL,
    STATE_DISCOVERED,
    STATE_FETCH_FAILED,
    STATE_REFERRED,
    STATE_SOLD,
    STATE_STATIC_PARSED,
    STATE_TABLE_SCHEMA,
    STATE_WITHDRAWN,
    TERMINAL_STATES,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _norm_url(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def normalize_state(value: object) -> str:
    state = str(value or "").strip().lower()
    if state in ALLOWED_LISTING_STATES:
        return state
    return STATE_DISCOVERED


@dataclass(frozen=True)
class ListingObservation:
    url: str
    observed_at: str
    run_id: str = ""
    is_live: bool = False
    has_sale_price: bool = False
    is_referred: bool = False
    is_withdrawn: bool = False
    fetch_failed: bool = False
    current_price: object = ""
    bid_count: object = ""
    time_remaining: object = ""
    evidence: str = ""
    fetch_error: str = ""


@dataclass(frozen=True)
class TransitionDecision:
    state: str
    reason_code: str
    terminal_reason: str
    fetch_fail_count: int
    last_fetch_error: str
    last_evidence: str


def evaluate_transition(
    previous_state: object,
    observation: ListingObservation,
    *,
    previous_fetch_fail_count: int = 0,
    fetch_fail_dead_threshold: int = 3,
) -> TransitionDecision:
    prev = normalize_state(previous_state)
    prev_fail_count = max(0, int(previous_fetch_fail_count or 0))
    evidence = str(observation.evidence or "").strip()

    # Terminal states are one-way unless explicitly unlocked in a later phase.
    if prev in TERMINAL_STATES:
        return TransitionDecision(
            state=prev,
            reason_code="TERMINAL_LOCK",
            terminal_reason=prev,
            fetch_fail_count=0,
            last_fetch_error="",
            last_evidence=evidence,
        )

    if observation.fetch_failed:
        next_fail_count = prev_fail_count + 1
        if next_fail_count >= fetch_fail_dead_threshold:
            return TransitionDecision(
                state=STATE_DEAD_URL,
                reason_code="FETCH_FAILED_THRESHOLD",
                terminal_reason="dead_url_after_retries",
                fetch_fail_count=next_fail_count,
                last_fetch_error=str(observation.fetch_error or "fetch_failed"),
                last_evidence=evidence,
            )
        # Keep prior lifecycle state when possible; mark fetch failure metadata.
        fallback_state = prev if prev in ALLOWED_LISTING_STATES else STATE_FETCH_FAILED
        return TransitionDecision(
            state=fallback_state,
            reason_code="FETCH_FAILED",
            terminal_reason="",
            fetch_fail_count=next_fail_count,
            last_fetch_error=str(observation.fetch_error or "fetch_failed"),
            last_evidence=evidence,
        )

    if observation.has_sale_price:
        return TransitionDecision(
            state=STATE_SOLD,
            reason_code="EVIDENCE_FINAL_PRICE",
            terminal_reason="sold_with_final_price",
            fetch_fail_count=0,
            last_fetch_error="",
            last_evidence=evidence,
        )
    if observation.is_referred:
        return TransitionDecision(
            state=STATE_REFERRED,
            reason_code="EVIDENCE_REFERRED",
            terminal_reason="referred",
            fetch_fail_count=0,
            last_fetch_error="",
            last_evidence=evidence,
        )
    if observation.is_withdrawn:
        return TransitionDecision(
            state=STATE_WITHDRAWN,
            reason_code="EVIDENCE_WITHDRAWN",
            terminal_reason="withdrawn_no_sale",
            fetch_fail_count=0,
            last_fetch_error="",
            last_evidence=evidence,
        )
    if observation.is_live:
        return TransitionDecision(
            state=STATE_ACTIVE,
            reason_code="EVIDENCE_LIVE_AUCTION",
            terminal_reason="",
            fetch_fail_count=0,
            last_fetch_error="",
            last_evidence=evidence,
        )

    if prev == STATE_DISCOVERED:
        next_state = STATE_STATIC_PARSED
    elif prev == STATE_FETCH_FAILED:
        next_state = STATE_STATIC_PARSED
    else:
        next_state = prev
    return TransitionDecision(
        state=next_state,
        reason_code="NO_TERMINAL_EVIDENCE",
        terminal_reason="",
        fetch_fail_count=0,
        last_fetch_error="",
        last_evidence=evidence,
    )


def ensure_state_schema(df: pd.DataFrame | None = None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=STATE_TABLE_SCHEMA)
    out = df.copy()
    for column in STATE_TABLE_SCHEMA:
        if column not in out.columns:
            out[column] = ""
    out = out.reindex(columns=STATE_TABLE_SCHEMA)
    return out.astype({column: "object" for column in STATE_TABLE_SCHEMA})


def upsert_state_row(
    state_df: pd.DataFrame,
    observation: ListingObservation,
    *,
    previous_state_hint: str = "",
    fetch_fail_dead_threshold: int = 3,
) -> tuple[pd.DataFrame, TransitionDecision]:
    out = ensure_state_schema(state_df)
    norm_url = _norm_url(observation.url)
    if not norm_url:
        raise ValueError("ListingObservation.url is required")

    if out.empty:
        match_idx: list[int] = []
    else:
        norm_series = out["url"].astype(str).str.strip().str.lower()
        match_idx = out.index[norm_series == norm_url].tolist()

    if match_idx:
        idx = int(match_idx[-1])
        previous_row = out.loc[idx].to_dict()
        previous_state = previous_row.get("state", "")
        previous_fail_count = int(previous_row.get("fetch_fail_count", 0) or 0)
    else:
        idx = None
        previous_row = {}
        previous_state = previous_state_hint or STATE_DISCOVERED
        previous_fail_count = 0

    decision = evaluate_transition(
        previous_state=previous_state,
        observation=observation,
        previous_fetch_fail_count=previous_fail_count,
        fetch_fail_dead_threshold=fetch_fail_dead_threshold,
    )

    payload = {column: previous_row.get(column, "") for column in STATE_TABLE_SCHEMA}
    payload["url"] = observation.url.strip()
    payload["state"] = decision.state
    payload["state_updated_at"] = observation.observed_at or _utc_now_iso()
    payload["run_id"] = observation.run_id
    payload["last_evidence"] = decision.last_evidence
    payload["fetch_fail_count"] = decision.fetch_fail_count
    payload["last_fetch_error"] = decision.last_fetch_error
    payload["terminal_reason"] = decision.terminal_reason

    if not observation.fetch_failed:
        payload["last_seen_at"] = observation.observed_at or _utc_now_iso()
    if observation.current_price not in ("", None):
        payload["current_price"] = observation.current_price
    if observation.bid_count not in ("", None):
        payload["bid_count"] = observation.bid_count
    if observation.time_remaining not in ("", None):
        payload["time_remaining"] = observation.time_remaining

    row_df = ensure_state_schema(pd.DataFrame([payload]))
    if idx is None:
        if out.empty:
            out = row_df.copy()
        else:
            out = pd.concat([out, row_df], ignore_index=True, sort=False)
    else:
        out = out.drop(index=idx)
        out = pd.concat([out, row_df], ignore_index=True, sort=False)
    out = ensure_state_schema(out).drop_duplicates(subset=["url"], keep="last").reset_index(drop=True)
    return out, decision


def upsert_state_rows(
    state_df: pd.DataFrame,
    observations: Iterable[ListingObservation],
    *,
    fetch_fail_dead_threshold: int = 3,
) -> pd.DataFrame:
    out = ensure_state_schema(state_df)
    for observation in observations:
        out, _ = upsert_state_row(
            out,
            observation,
            fetch_fail_dead_threshold=fetch_fail_dead_threshold,
        )
    return out
