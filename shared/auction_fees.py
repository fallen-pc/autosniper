"""Lot-bound Slattery fee evidence and strict auction-operator identification.

Slattery's public asset calculator sums every applicable chargePrices row: a
positive flat amount, otherwise the larger of percentage and minimum, otherwise
the minimum. The calculator also adds 1.65% to bid plus premium below $5,000.
Observed 2026-09-11 in official chunk 5613-8a9e61b2af6b533f.js. Its generic
fallback when chargePrices is absent is intentionally NOT used here.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit


FEE_FIELDS = (
    "auction_fee_schedule", "auction_fee_evidence_url",
    "auction_fee_evidence_text", "auction_fee_status",
)
_HOSTS = {
    "grays.com": "grays", "graysonline.com": "grays",
    "slatteryauctions.com.au": "slattery", "pickles.com.au": "pickles",
    "manheim.com.au": "manheim",
}
_EXTRACTION_REASONS = {
    "Unsupported Slattery charge category", "Missing or duplicate Slattery charge identity",
    "Invalid numeric fee term", "Missing numeric fee term", "Invalid Slattery fee range",
    "Incomplete Slattery fee ranges", "Slattery fee schedule has no upper range",
    "Slattery fee asset does not match the listing", "Slattery fee auction does not match the listing",
}


class FeeEvidenceError(ValueError):
    """A purchase estimate cannot be supported by the supplied lot evidence."""


def _text(value: Any) -> str:
    text = str(value).strip() if value is not None else ""
    return "" if text.lower() in {"nan", "none", "<na>"} else text


def url_operator(url: Any) -> str:
    try:
        parsed = urlsplit(_text(url))
        if parsed.scheme not in {"https", "http"} or parsed.username or parsed.password:
            return "unknown"
        host = (parsed.hostname or "").lower().rstrip(".")
        for domain, operator in _HOSTS.items():
            if host == domain or host == "www." + domain:
                return operator
    except ValueError:
        pass
    return "unknown"


def auction_operator(listing: Mapping[str, Any]) -> str:
    operator = url_operator(listing.get("url"))
    declared = {
        _text(listing.get(key)).lower()
        for key in ("auction_operator", "source", "platform")
        if _text(listing.get(key))
    }
    declared = {value for value in declared if value in set(_HOSTS.values())}
    if len(declared) > 1 or (declared and operator not in declared):
        return "conflict"
    return operator


def _lot_key(url: Any) -> tuple[str, str, str]:
    try:
        parsed = urlsplit(_text(url))
    except ValueError:
        raise FeeEvidenceError("Invalid lot URL in fee evidence") from None
    # Referral tracking is provenance; auctionId remains part of lot identity.
    query = [(k, v) for k, v in parse_qsl(parsed.query) if not k.lower().startswith("utm_")]
    return url_operator(url), parsed.path.rstrip("/"), urlencode(sorted(query))


def _number(value: Any, *, nullable: bool = False) -> float | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool):
        raise FeeEvidenceError("Invalid numeric fee term")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise FeeEvidenceError("Missing numeric fee term") from None
    if not math.isfinite(number) or number < 0:
        raise FeeEvidenceError("Invalid numeric fee term")
    return number


def _validate_schedule(schedule: Any, listing_url: str) -> dict[str, Any]:
    if not isinstance(schedule, dict) or schedule.get("version") != 1 or schedule.get("operator") != "slattery":
        raise FeeEvidenceError("Missing supported lot-specific Slattery fee schedule")
    if url_operator(listing_url) != "slattery" or _lot_key(schedule.get("listing_url")) != _lot_key(listing_url):
        raise FeeEvidenceError("Slattery fee evidence belongs to a different lot")
    try:
        observed = datetime.fromisoformat(_text(schedule.get("observed_at")).replace("Z", "+00:00"))
    except ValueError:
        raise FeeEvidenceError("Missing fee observation time") from None
    if observed.tzinfo is None:
        raise FeeEvidenceError("Missing fee observation time")
    rows = schedule.get("charges")
    if not isinstance(rows, list) or not rows:
        raise FeeEvidenceError("Missing lot-specific Slattery charges")
    normalized = []
    for row in rows:
        if not isinstance(row, dict):
            raise FeeEvidenceError("Invalid Slattery fee row")
        lower = _number(row.get("lower"))
        upper = _number(row.get("upper"), nullable=True)
        if upper is not None and upper < lower:
            raise FeeEvidenceError("Invalid Slattery fee range")
        normalized.append({
            "lower": lower, "upper": upper,
            "flat": _number(row.get("flat")), "rate": _number(row.get("rate")),
            "minimum": _number(row.get("minimum")),
        })
    # Refuse partial schedules: the proxy solver needs every possible lower bid.
    # A purchase must have a positive price. Some real custom schedules start
    # at $0.01 rather than including a hypothetical zero-dollar purchase.
    coverage_end = 0.0
    for row in sorted(normalized, key=lambda item: item["lower"]):
        if row["lower"] > coverage_end + 0.01000001:
            raise FeeEvidenceError("Incomplete Slattery fee ranges")
        coverage_end = max(coverage_end, row["upper"] if row["upper"] is not None else math.inf)
    if coverage_end != math.inf:
        raise FeeEvidenceError("Slattery fee schedule has no upper range")
    return {**schedule, "charges": normalized}


def extract_slattery_fee_fields(record: Mapping[str, Any], canonical_url: str) -> dict[str, str]:
    """Use only the matched asset's structured GST-inclusive buyer charges."""
    result = {field: "" for field in FEE_FIELDS}
    result["auction_fee_evidence_url"] = canonical_url
    result["auction_fee_status"] = "missing"
    raw = record.get("chargePrices")
    if not isinstance(raw, list) or not raw:
        return result
    try:
        parsed = urlsplit(canonical_url)
        asset_id = parsed.path.rstrip("/").rsplit("/", 1)[-1]
        if not parsed.path.startswith("/assets/") or asset_id not in {_text(record.get("id")), _text(record.get("sfid"))}:
            raise FeeEvidenceError("Slattery fee asset does not match the listing")
        aliases = record.get("_auction_aliases")
        aliases = aliases if isinstance(aliases, (list, tuple, set)) else []
        auction_ids = {_text(record.get("auctionId")), *map(_text, aliases)}
        auction = record.get("auction")
        if isinstance(auction, dict) and _text(auction.get("id")) == _text(record.get("auctionId")):
            auction_ids.update({_text(auction.get("id")), _text(auction.get("sfid"))})
        requested_auction = dict(parse_qsl(parsed.query)).get("auctionId")
        if requested_auction and requested_auction not in auction_ids:
            raise FeeEvidenceError("Slattery fee auction does not match the listing")
        charges = []
        seen = set()
        for row in raw:
            if not isinstance(row, dict) or row.get("chargeType") != "Buyer Charge" or row.get("assetType") != "Motor Vehicle":
                raise FeeEvidenceError("Unsupported Slattery charge category")
            identity = row.get("id") or row.get("sfid")
            if identity is None or str(identity) in seen:
                raise FeeEvidenceError("Missing or duplicate Slattery charge identity")
            seen.add(str(identity))
            charges.append({
                "lower": row.get("salesPriceLowerBound"), "upper": row.get("salesPriceUpperBound"),
                "flat": row.get("flatAmountInclGst"), "rate": row.get("chargeRateInclGst"),
                "minimum": row.get("chargeRateMinimumInclGst"),
            })
        schedule = _validate_schedule({
            "version": 1, "operator": "slattery", "listing_url": canonical_url,
            "observed_at": datetime.now(timezone.utc).isoformat(), "charges": charges,
        }, canonical_url)
        result["auction_fee_schedule"] = json.dumps(schedule, sort_keys=True, separators=(",", ":"))
        result["auction_fee_evidence_text"] = "Matched asset chargePrices, GST inclusive; site calculator card fee included below $5,000 bid plus premium."
        result["auction_fee_status"] = "verified_schedule"
    except (FeeEvidenceError, ValueError) as exc:
        result["auction_fee_status"] = "unsupported"
        result["auction_fee_evidence_text"] = str(exc)
    return result


def slattery_schedule(listing: Mapping[str, Any]) -> dict[str, Any]:
    if auction_operator(listing) != "slattery":
        raise FeeEvidenceError("Auction operator conflicts with the listing URL")
    status = _text(listing.get("auction_fee_status"))
    if status == "unsupported":
        reason = _text(listing.get("auction_fee_evidence_text"))
        message = f"Unsupported Slattery fee evidence: {reason}" if reason in _EXTRACTION_REASONS else "Unsupported lot-specific Slattery fee evidence"
        raise FeeEvidenceError(message)
    if status != "verified_schedule":
        raise FeeEvidenceError("Missing verified lot-specific Slattery fee evidence")
    raw = listing.get("auction_fee_schedule")
    try:
        schedule = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        raise FeeEvidenceError("Invalid Slattery fee evidence JSON") from None
    if _lot_key(listing.get("auction_fee_evidence_url")) != _lot_key(listing.get("url")):
        raise FeeEvidenceError("Slattery fee evidence URL does not match the listing")
    return _validate_schedule(schedule, _text(listing.get("url")))


def fee_evidence_problem(listing: Mapping[str, Any]) -> str:
    operator = auction_operator(listing)
    if operator == "conflict":
        return "Auction operator conflicts with the listing URL; verify the selling platform."
    if operator == "slattery":
        try:
            slattery_schedule(listing)
        except FeeEvidenceError as exc:
            return str(exc)
    return ""


def _premium(bid: float, schedule: Mapping[str, Any]) -> float:
    applicable = [r for r in schedule["charges"] if bid >= r["lower"] and (r["upper"] is None or bid <= r["upper"])]
    if not applicable:
        if bid == 0:
            return 0.0
        raise FeeEvidenceError("No Slattery fee range covers this bid")
    return sum(r["flat"] if r["flat"] > 0 else max(bid * r["rate"] / 100, r["minimum"]) for r in applicable)


def slattery_buyer_charges(bid: float, listing: Mapping[str, Any]) -> float:
    schedule = slattery_schedule(listing)
    bid = float(Decimal(str(bid)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    premium = _premium(bid, schedule)
    card = (bid + premium) * 0.0165 if bid + premium < 5000 else 0.0
    return premium + card


def slattery_fee_breakpoints(listing: Mapping[str, Any]) -> list[float]:
    """Prices before fee drops, to protect every possible lower proxy win."""
    schedule = slattery_schedule(listing)
    points = {0.0}
    for row in schedule["charges"]:
        points.add(row["lower"])
        if row["lower"] > 0:
            points.add(round(row["lower"] - 0.01, 2))
        if row["upper"] is not None:
            points.add(row["upper"])
    # Card threshold can fall inside a fee band. Locate it in each band; do
    # not assume the total is monotonic across the schedule's discontinuities.
    boundaries = sorted(points | {5000.0})
    for left, right in zip(boundaries, boundaries[1:]):
        lo, hi = int(math.ceil(left * 100)), int(math.floor(right * 100))
        if lo >= hi or hi / 100 > 5000:
            continue
        if lo / 100 + _premium(lo / 100, schedule) >= 5000 or hi / 100 + _premium(hi / 100, schedule) < 5000:
            continue
        while lo + 1 < hi:
            mid = (lo + hi) // 2
            if mid / 100 + _premium(mid / 100, schedule) < 5000:
                lo = mid
            else:
                hi = mid
        points.update({lo / 100, hi / 100})
    return sorted(points)
