from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple


# ----------------------------
# Tunables (opinionated defaults)
# ----------------------------
TOP_BUY_MIN_MARGIN_PCT = 20.0          # label requirement
TOP_BUY_ENTRY_MIN_MARGIN_PCT = 18.0    # if you want a softer internal gate
KM_PCTL_MAX = 0.45                     # <=45th percentile = "low km" (curve-relative)

AT_MEDIAN_TOL_PCT = 0.05               # ±5%
CS_EST_TOL_PCT = 0.07                  # ±7%

HIST_MATCH_MIN_COUNT = 2
HIST_KM_TOL_PCT = 0.15                 # ±15% km band
HIST_PRICE_TOL_PCT = 0.15              # optional: keep loose; confirm-only

REQUIRED_CURVE_CONFIDENCE = 0.85

# If you maintain pill colors as strings:
GREEN = "green"
YELLOW = "yellow"
ORANGE = "orange"
RED = "red"


@dataclass
class TopBuyResult:
    is_top_buy: bool
    reasons_failed: List[str]
    reasons_passed: List[str]


def _pct_diff(a: float, b: float) -> float:
    """Absolute percentage difference, e.g., 0.05 == 5%."""
    if a is None or b is None:
        return 1.0
    denom = max(abs(b), 1.0)
    return abs(a - b) / denom


def _get(v: Dict[str, Any], path: str, default=None):
    """Safe nested getter: 'a.b.c'."""
    cur: Any = v
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def top_buy_gate_check(vehicle: Dict[str, Any]) -> TopBuyResult:
    """
    Hard-gated TOP BUY.

    Expected vehicle fields (adjust paths to your schema):
      - vehicle["pills"] : dict of pill_name -> color string ("green"/"yellow"/"orange"/"red")
          OR precomputed: vehicle["pill_summary"] with same info
      - vehicle["damage"] : dict with counts (cosmetic_panels, glass_present, replacement_present)
      - vehicle["curve"] : dict with {covered: bool, confidence: float, km_percentile: float}
      - vehicle["market"] : dict with {autotrader_median, carsales_estimate, listings_cluster_ok: bool}
      - vehicle["historical"] : dict with {matches: list[dict]} where each match has km, spec_match: bool
      - vehicle["ai_sanity"] : dict with {status: "PASS"/"FAIL", new_risks: list[str]}
      - vehicle["profit_margin_pct"] : float (based on curve resale, fees, buffers; not auction price)
    """
    failed: List[str] = []
    passed: List[str] = []

    # ----------------------------
    # Gate 1: Zero defects (all pills green, and explicitly no cosmetic/glass/replace)
    # ----------------------------
    pills: Dict[str, str] = _get(vehicle, "pills", {}) or _get(vehicle, "pill_summary", {}) or {}
    if not pills:
        failed.append("G1_PILLS_MISSING")
    else:
        non_green = [k for k, c in pills.items() if str(c).lower() != GREEN]
        if non_green:
            failed.append(f"G1_PILLS_NOT_ALL_GREEN: {non_green}")
        else:
            passed.append("G1_ALL_PILLS_GREEN")

    cosmetic_panels = int(_get(vehicle, "damage.cosmetic_panels", 0) or 0)
    glass_present = bool(_get(vehicle, "damage.glass_present", False))
    replacement_present = bool(_get(vehicle, "damage.replacement_present", False))
    unknown_present = bool(_get(vehicle, "damage.unknown_present", False))

    # Top Buy must be clean
    if cosmetic_panels != 0:
        failed.append(f"G1_COSMETIC_PRESENT: panels={cosmetic_panels}")
    if glass_present:
        failed.append("G1_GLASS_ISSUE_PRESENT")
    if replacement_present:
        failed.append("G1_REPLACEMENT_PRESENT")
    if unknown_present:
        failed.append("G1_UNKNOWN_PRESENT")
    if (cosmetic_panels == 0) and (not glass_present) and (not replacement_present) and (not unknown_present):
        passed.append("G1_NO_DEFECTS_CONFIRMED")

    # ----------------------------
    # Gate 2: Low KM (curve-relative percentile)
    # ----------------------------
    km_pctl = _get(vehicle, "curve.km_percentile", None)
    if km_pctl is None:
        failed.append("G2_KM_PERCENTILE_MISSING")
    else:
        try:
            km_pctl = float(km_pctl)
            if km_pctl <= KM_PCTL_MAX:
                passed.append(f"G2_LOW_KM_OK: pctl={km_pctl:.2f}")
            else:
                failed.append(f"G2_LOW_KM_FAIL: pctl={km_pctl:.2f}")
        except Exception:
            failed.append("G2_KM_PERCENTILE_BAD_VALUE")

    # ----------------------------
    # Gate 3: Curve coverage (mandatory, confidence threshold)
    # ----------------------------
    curve_covered = bool(_get(vehicle, "curve.covered", False))
    curve_conf = _get(vehicle, "curve.confidence", None)
    if not curve_covered:
        failed.append("G3_NO_CURVE_COVERAGE")
    else:
        passed.append("G3_CURVE_COVERED")

    if curve_conf is None:
        failed.append("G3_CURVE_CONFIDENCE_MISSING")
    else:
        try:
            curve_conf = float(curve_conf)
            if curve_conf >= REQUIRED_CURVE_CONFIDENCE:
                passed.append(f"G3_CURVE_CONF_OK: {curve_conf:.2f}")
            else:
                failed.append(f"G3_CURVE_CONF_LOW: {curve_conf:.2f}")
        except Exception:
            failed.append("G3_CURVE_CONFIDENCE_BAD_VALUE")

    # ----------------------------
    # Gate 4: Historical auction match (confirmation only)
    # ----------------------------
    matches = _get(vehicle, "historical.matches", []) or []
    match_count = _get(vehicle, "historical.match_count", len(matches))
    try:
        match_count = int(match_count or 0)
    except (TypeError, ValueError):
        match_count = len(matches)
    if len(matches) < HIST_MATCH_MIN_COUNT:
        if match_count >= HIST_MATCH_MIN_COUNT:
            passed.append(f"G4_HIST_MATCH_COUNT_OK: count={match_count}")
        else:
            failed.append(f"G4_HIST_MATCH_COUNT_FAIL: {match_count}")
    else:
        # enforce spec_match and km proximity
        target_km = _get(vehicle, "odometer_reading", None)
        good = 0
        for m in matches:
            if not bool(m.get("spec_match", False)):
                continue
            if target_km is not None and m.get("km") is not None:
                try:
                    km = float(m["km"])
                    tk = float(target_km)
                    if tk > 0 and abs(km - tk) / tk > HIST_KM_TOL_PCT:
                        continue
                except Exception:
                    continue
            good += 1

        if good >= HIST_MATCH_MIN_COUNT:
            passed.append(f"G4_HIST_MATCH_OK: good={good}")
        else:
            failed.append(f"G4_HIST_MATCH_QUALITY_FAIL: good={good}")

    # ----------------------------
    # Gate 5: Market alignment (Autotrader + Carsales vs curve resale)
    # ----------------------------
    curve_resale = _get(vehicle, "resale_estimate", None) or _get(vehicle, "curve.resale_estimate", None)
    at_med = _get(vehicle, "market.autotrader_median", None)
    cs_est = _get(vehicle, "market.carsales_estimate", None)
    cluster_ok = bool(_get(vehicle, "market.listings_cluster_ok", False))

    if curve_resale is None:
        failed.append("G5_CURVE_RESALE_MISSING")
    else:
        try:
            curve_resale = float(curve_resale)
        except Exception:
            failed.append("G5_CURVE_RESALE_BAD_VALUE")
            curve_resale = None

    if curve_resale is not None:
        if at_med is None:
            failed.append("G5_AUTOTRADER_MEDIAN_MISSING")
        else:
            try:
                at_med = float(at_med)
                if _pct_diff(at_med, curve_resale) <= AT_MEDIAN_TOL_PCT:
                    passed.append("G5_AUTOTRADER_ALIGN_OK")
                else:
                    failed.append(f"G5_AUTOTRADER_ALIGN_FAIL: diff={_pct_diff(at_med, curve_resale):.2%}")
            except Exception:
                failed.append("G5_AUTOTRADER_MEDIAN_BAD_VALUE")

        if cs_est is None:
            failed.append("G5_CARSALES_EST_MISSING")
        else:
            try:
                cs_est = float(cs_est)
                if _pct_diff(cs_est, curve_resale) <= CS_EST_TOL_PCT:
                    passed.append("G5_CARSALES_ALIGN_OK")
                else:
                    failed.append(f"G5_CARSALES_ALIGN_FAIL: diff={_pct_diff(cs_est, curve_resale):.2%}")
            except Exception:
                failed.append("G5_CARSALES_EST_BAD_VALUE")

        if cluster_ok:
            passed.append("G5_LISTINGS_CLUSTER_OK")
        else:
            failed.append("G5_LISTINGS_CLUSTER_FAIL")

    # ----------------------------
    # Gate 6: AI sanity pass (no new risks)
    # ----------------------------
    ai_status = str(_get(vehicle, "ai_sanity.status", "") or "").upper()
    ai_new_risks = _get(vehicle, "ai_sanity.new_risks", []) or []

    if ai_status != "PASS":
        failed.append(f"G6_AI_SANITY_FAIL: status={ai_status or 'MISSING'}")
    elif ai_new_risks:
        failed.append(f"G6_AI_FOUND_NEW_RISKS: {ai_new_risks}")
    else:
        passed.append("G6_AI_SANITY_OK")

    # ----------------------------
    # Gate 7: Profit margin (label requirement)
    # ----------------------------
    pm = _get(vehicle, "profit_margin_pct", None)
    if pm is None:
        failed.append("G7_PROFIT_MARGIN_MISSING")
    else:
        try:
            pm = float(pm)
            if pm >= TOP_BUY_MIN_MARGIN_PCT:
                passed.append(f"G7_MARGIN_OK: {pm:.1f}%")
            else:
                failed.append(f"G7_MARGIN_TOO_LOW: {pm:.1f}% (<{TOP_BUY_MIN_MARGIN_PCT:.0f}%)")
        except Exception:
            failed.append("G7_PROFIT_MARGIN_BAD_VALUE")

    # Final
    is_top_buy = len(failed) == 0
    return TopBuyResult(is_top_buy=is_top_buy, reasons_failed=failed, reasons_passed=passed)


def apply_top_buy_behavior(
    base_max_bid: int,
    top_buy: TopBuyResult,
    standard_uncertainty_buffer: int,
    top_buy_uncertainty_buffer: int = 400,
) -> Tuple[int, str]:
    """
    TOP BUY changes *only* uncertainty buffer aggressiveness (not resale).
    Use after you’ve computed a base max bid and after repair deductions (which should be zero for Top Buy).

    Returns (adjusted_max_bid, badge_label)
    """
    if not top_buy.is_top_buy:
        return max(0, int(base_max_bid) - int(standard_uncertainty_buffer)), ""

    adjusted = max(0, int(base_max_bid) - int(top_buy_uncertainty_buffer))
    return adjusted, "TOP BUY"
