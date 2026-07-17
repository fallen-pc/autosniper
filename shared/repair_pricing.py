"""Repair pricing and hard-avoid logic for auction condition notes."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import html
import json
import re

import pandas as pd
import yaml

from shared.condition_normalizer import estimate_component_count
from shared.repair_features import build_repair_features


PANEL_RATE = 300
PANEL_CAP = 3

WINDSCREEN_STD = 350
WINDSCREEN_ADAS = 500

REPLACEMENT_COSTS = {
    "door": 500,
    "guard": 400,
    "bumper": 600,
    "tailgate": 700,
    "mirror": 250,
}

HARD_CAPS = {
    "cosmetic_only": 900,
    "cosmetic_plus_glass": 1200,
    "with_replacement": 1500,
}

# For low-value/older cars, pure cosmetic damage (scuffs, minor panel marks) often
# isn't worth fixing before a flip -- the $900 flat cap can still eat a big chunk of
# a cheap car's value. When a vehicle_value is supplied, the cosmetic-only cap scales
# down to this fraction of value instead, so a $10k car caps at $300 rather than $900.
# Cars above ~$30k are unaffected since 3% of value exceeds the existing $900 cap.
COSMETIC_CAP_PCT_OF_VALUE = 0.03

RISK_BUFFERS = {
    "unknown_photos": 300,
    "no_closeups": 300,
    "interstate_yard": 200,
    "paint_black_or_white": 100,
}

SEVERITY_MULTIPLIERS = {
    "minor": 1.0,
    "moderate": 1.5,
    "major": 2.5,
}

V2_DICTIONARY_PATH = Path(__file__).resolve().parent.parent / "config" / "condition_dictionary_v2.yaml"

V2_HARD_AVOID_CANONICALS = {
    "engine_fault",
    "transmission_fault",
    "warning_light",
}

STRUCTURAL_HARD_AVOID_CANONICALS = {
    "structural_damage",
}

V2_UNKNOWN_CANONICALS = {
    "boilerplate_refer_photos",
    "boilerplate_arrange_inspection",
}

V2_GLASS_CANONICALS = {
    "windscreen_damage",
    "window_damage",
}

V2_REPLACEMENT_COSTS = {
    "lighting_damage": 250,
    "mirror_light_damage": 250,
    "bumper_damage": 600,
    "replacement_required": 600,
    "door_handle_damage": 250,
    "fuel_flap_damage": 250,
    "sunroof_damage": 600,
    "battery_issue": 300,
    "tyre_replacement": 180,
    "wheel_missing": 250,
    "control_damage": 250,
    "seat_damage": 250,
    "seat_issue": 150,
    "interior_trim_damage": 250,
    "structural_damage": 900,
    "hail_damage": 900,
    "corrosion_damage": 1200,
}

REPAIR_PRICING_SCHEDULE_PATH = (
    Path(__file__).resolve().parent.parent / "CSV_data" / "reports" / "repair_pricing_schedule.csv"
)

# Schedule rows priced from wrecker listings are part-only (no paint/fitting labour),
# so they may only raise the hardcoded fitted-cost floor, never lower it. Every other
# pricing method represents a full-job price and overrides the hardcoded value.
PART_ONLY_PRICING_METHODS = {"wrecker_part_price"}

# ADAS windscreens add a camera recalibration on top of the glass job.
WINDSCREEN_ADAS_PREMIUM = WINDSCREEN_ADAS - WINDSCREEN_STD


@lru_cache(maxsize=1)
def _schedule_cost_overrides() -> Dict[str, int]:
    """canonical_defect -> default_estimate from the curated repair pricing schedule."""
    try:
        df = pd.read_csv(REPAIR_PRICING_SCHEDULE_PATH)
    except Exception:
        return {}
    overrides: Dict[str, int] = {}
    for _, row in df.iterrows():
        canonical = str(row.get("canonical_defect") or "").strip()
        method = str(row.get("pricing_method") or "").strip()
        try:
            default = float(row.get("default_estimate"))
        except (TypeError, ValueError):
            continue
        if not canonical or not default > 0:
            continue
        if method in PART_ONLY_PRICING_METHODS:
            overrides[canonical] = int(max(V2_REPLACEMENT_COSTS.get(canonical, 0), default))
        else:
            overrides[canonical] = int(default)
    return overrides


def _effective_cost(canonical: str, fallback: int) -> int:
    override = _schedule_cost_overrides().get(canonical)
    if override is not None:
        return override
    return int(V2_REPLACEMENT_COSTS.get(canonical, fallback))


def _windscreen_glass_cost(adas_windscreen: bool) -> int:
    base = _effective_cost("windscreen_damage", WINDSCREEN_STD)
    return base + WINDSCREEN_ADAS_PREMIUM if adas_windscreen else base

PANEL_LOCATION_TERMS = (
    "door",
    "guard",
    "bumper",
    "bar",
    "bonnet",
    "bootlid",
    "boot",
    "tailgate",
    "roof",
    "panel",
    "mirror",
    "window",
    "headlight",
    "head light",
    "tail light",
    "taillight",
)

DAMAGE_WORD_RE = re.compile(
    r"\b(crack|cracked|broken|missing|damaged|damage|not working|torn|chip|chipped)\b",
    re.IGNORECASE,
)
REPLACEMENT_TARGET_RE = re.compile(
    r"\b(headlight|head light|tail light|taillight|indicator|mirror|bumper|bar|door handle)\b",
    re.IGNORECASE,
)
CONDITION_FRAGMENT_RE = re.compile(r"[.;|,\r\n]+")
CONDITION_SECTION_BOUNDARY_RE = re.compile(
    r"(?<=[a-z0-9])(?=(?:interior|exterior|mechanical|engine|transmission|body|paint|glass|windscreen):)",
    re.IGNORECASE,
)
BODY_LOCATION_FRAGMENT_RE = re.compile(
    r"^(?:(?:front|rear|left|right|lhr|rhr|lh|rh|driver'?s?|passenger(?: side)?)\s+)*"
    r"(?:roof|bonnet|bumper|bar|door|doors|boot|bootlid|tailgate|guard|panel|quarter|mirror|"
    r"headlight|head light|tail light|taillight|tail lamp|lamp|side step|side steps)"
    r"(?:\s*(?:and|&)\s*(?:(?:front|rear|left|right|lhr|rhr|lh|rh|driver'?s?|passenger(?: side)?)\s+)*"
    r"(?:roof|bonnet|bumper|bar|door|doors|boot|bootlid|tailgate|guard|panel|quarter|mirror|"
    r"headlight|head light|tail light|taillight|tail lamp|lamp|side step|side steps))*\.?$",
    re.IGNORECASE,
)
CONTEXT_DAMAGE_RE = re.compile(
    r"\b(?P<context>(?:(?:small|medium|large|minor|major|light|heavy)\s+)?"
    r"(?:scratch(?:es)?|scuff(?:s)?|dent(?:s)?|damage|body/panel damage|panel damage|"
    r"paint damage|crack(?:ed)?|broken|hazed|faded|rust|corrosion)\b(?:\s+(?:on|to))?)",
    re.IGNORECASE,
)

MECH_AVOID_PATTERNS = [
    r"\bengine light\b",
    r"\b(epc|vsa|master warning) light\b",
    r"\bwarning lights? on dash\b",
    r"\bengine (light|warning) on\b",
    r"\bother warning light on\b",
    r"\babs light on\b",
    r"\bairbag light on\b",
    r"\btraction control light on\b",
    r"\bcheck engine\b",
    r"\bengine noise\b",
    r"\bengine idling rough\b",
    r"\bengine lacks power\b",
    r"\b(engine|motor)\b.*\b(requires attention|needs attention|issues?|tick(?:ing)?)\b",
    r"\bsteering\b(?!\s+wheel).*\b(requires attention|needs attention|noise|vibration|fault|issues?)\b",
    r"\bdriveline\b.*\b(attention|fault|issues?|noise)\b",
    r"\b(gearbox|transmission)\b.*\bshudder",
    r"\bcoolant\b.*\b(leak|issues?|fault|loss)\b",
    r"\b(black|white|blue|excessive) smoke\b",
    r"\bexhaust smoke\b",
    r"\bsmoke from (?:the )?exhaust\b",
    r"\bblowing smoke\b",
    r"\bsmoke (?:evident|visible|observed)\b",
    r"\bnoise (?:whilst|while|when) driving\b",
    r"\b(vehicle\s+)?stall(?:s|ing|ed)?\b",
    r"\bhead gasket\b",
    r"\btransmission\b.*\b(attention|fault|issue|noise|slip)\b",
    r"\bgearbox\b.*\b(attention|fault|issue|noise|slip)\b",
    r"\bdiff\b.*\b(attention|fault|issue|noise|bush(?:es)?|leak)\b",
    r"\boverheating\b",
    r"\bcooling system\b.*\brequires attention\b",
    r"\bcooling\b.*\b(leak|issue|fault)\b",
    r"\boil leak\b",
    r"\bpower steering\b.*\b(attention|fault|issue|leak)\b",
    r"\bdrivetrain\b.*\b(fault|issue)\b",
    r"\bsuspension\b.*\b(attention|fault|issue|noise)\b",
    r"\balignment\b.*\b(issue|pull)\b",
    r"\bbrakes?\b.*\b(attention|fault|issue|require|requires)\b",
    r"\bmechanical\b.*\b(attention|fault|issue|require|requires)\b",
    r"\bclutch\b.*\b(attention|fault|issue|slip)\b",
    r"\bdoes not start\b",
    r"\bwon't start\b",
    r"\bnot running\b",
    r"\bcannot be driven off site\b",
    r"\btilt tray\b.*\b(required|recommended)\b",
    r"\btowing required\b",
]

MECH_AVOID_RE = [re.compile(pattern, re.IGNORECASE) for pattern in MECH_AVOID_PATTERNS]


def normalise_condition_line(line: str) -> str:
    text = (line or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text.rstrip(" .;") + "." if text else ""


def _is_numbering_only_condition_fragment(line: str) -> bool:
    return bool(re.fullmatch(r"#?\d{1,3}\.?", str(line or "").strip()))


def _decode_condition_entities(text: str) -> str:
    decoded = str(text or "")
    for _ in range(5):
        next_value = html.unescape(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    return decoded


def split_condition_lines(text: str) -> List[str]:
    if not text:
        return []
    decoded_text = _decode_condition_entities(str(text))
    normalized_text = CONDITION_SECTION_BOUNDARY_RE.sub(". ", decoded_text)
    parts = CONDITION_FRAGMENT_RE.split(normalized_text)
    out: List[str] = []
    last_location_context = ""
    for part in parts:
        part = part.strip(" -")
        if not part:
            continue
        line = normalise_condition_line(part)
        if _is_numbering_only_condition_fragment(line):
            continue
        if last_location_context and BODY_LOCATION_FRAGMENT_RE.match(line):
            line = normalise_condition_line(f"{last_location_context} {line.rstrip('.')}")
        out.append(line)
        context_match = CONTEXT_DAMAGE_RE.search(line)
        if context_match:
            last_location_context = context_match.group("context").strip()
        elif not BODY_LOCATION_FRAGMENT_RE.match(line):
            last_location_context = ""
    seen = set()
    deduped: List[str] = []
    for line in out:
        key = line.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(line)
    return deduped


@dataclass(frozen=True)
class V2ConditionEntry:
    canonical_defect: str
    category: str
    severity_hint: str
    pattern: re.Pattern[str]


def _fragment_key(line: str) -> str:
    cleaned = re.sub(r"[^a-z0-9\s]", " ", str(line or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _mechanical_trigger_line(lines: List[str]) -> str | None:
    for line in lines:
        for regex in MECH_AVOID_RE:
            if regex.search(line):
                return line
    return None


def any_mechanical(lines: List[str]) -> bool:
    return _mechanical_trigger_line(lines) is not None


@dataclass
class RepairFragment:
    original_text: str
    normalized_text: str
    status: str
    category: str
    canonical_defects: List[str] = field(default_factory=list)
    pills: List[str] = field(default_factory=list)
    cost_estimate: int = 0
    hard_avoid_reason: str | None = None
    reasons: List[str] = field(default_factory=list)


REPAIR_COST_LOW_MULTIPLIER = 0.55   # p25 of low_estimate/default_estimate from pricing schedule
REPAIR_COST_HIGH_MULTIPLIER = 1.60  # median of high_estimate/default_estimate from pricing schedule


@dataclass
class RepairAssessment:
    hard_avoid: bool
    pills: List[str]
    cosmetic_panels: int
    glass_cost: int
    replacement_cost: int
    risk_buffer: int
    base_cost: int
    severity_level: str
    severity_multiplier: float
    total_cost: int
    reasons: List[str]
    hard_avoid_reason: str | None = None
    original_text: str = ""
    fragments: List[RepairFragment] = field(default_factory=list)
    total_cost_low: int = 0   # optimistic estimate (low repair scenario)
    total_cost_high: int = 0  # pessimistic estimate (used for bid deduction)


HARD_AVOID_BUCKETS = {
    "mechanical": {"pill": "MECHANICAL", "cost": 10_000},
    "structural": {"pill": "STRUCTURAL", "cost": 8_000},
    "unknown": {"pill": "UNKNOWN", "cost": 4_000},
}

REPAIR_GATE_GOOD_MAX = 600
REPAIR_GATE_MARGINAL_MAX = 2_500
REPAIR_GATE_NOT_VIABLE_MAX = 4_000

# The flat dollar gates above treat a $2,500 repair bill the same whether the car is
# worth $3,000 or $80,000. When a vehicle_value is supplied, each gate becomes
# whichever is LARGER of the flat floor above or this percentage of vehicle value --
# so cheap cars keep today's behaviour unchanged (the flat floor still binds below
# ~$12k-$16k of value) while higher-value cars get proportionally more repair
# headroom before being downgraded to Marginal/Not Viable/Avoid.
REPAIR_GATE_GOOD_PCT = 0.05
REPAIR_GATE_MARGINAL_PCT = 0.15
REPAIR_GATE_NOT_VIABLE_PCT = 0.25


def _repair_gate_thresholds(vehicle_value: float | None) -> tuple[float, float, float]:
    if not vehicle_value or vehicle_value <= 0:
        return (
            float(REPAIR_GATE_GOOD_MAX),
            float(REPAIR_GATE_MARGINAL_MAX),
            float(REPAIR_GATE_NOT_VIABLE_MAX),
        )
    good = max(REPAIR_GATE_GOOD_MAX, vehicle_value * REPAIR_GATE_GOOD_PCT)
    marginal = max(REPAIR_GATE_MARGINAL_MAX, vehicle_value * REPAIR_GATE_MARGINAL_PCT)
    not_viable = max(REPAIR_GATE_NOT_VIABLE_MAX, vehicle_value * REPAIR_GATE_NOT_VIABLE_PCT)
    return good, marginal, not_viable


def _hard_avoid_assessment(
    reason: str,
    *,
    severity_level: str,
    severity_multiplier: float,
    trigger_reason: str,
    original_text: str = "",
    lines: List[str] | None = None,
    trigger_line: str | None = None,
) -> RepairAssessment:
    bucket = HARD_AVOID_BUCKETS.get(reason, HARD_AVOID_BUCKETS["mechanical"])
    hard_cost = int(bucket["cost"])
    fragments: list[RepairFragment] = []
    for line in lines or []:
        is_trigger = line == trigger_line if trigger_line else False
        fragments.append(
            RepairFragment(
                original_text=line,
                normalized_text=_fragment_key(line),
                status="hard_avoid" if is_trigger else "not_assessed_after_hard_avoid",
                category=reason if is_trigger else "not_assessed",
                pills=[str(bucket["pill"])] if is_trigger else [],
                cost_estimate=hard_cost if is_trigger else 0,
                hard_avoid_reason=reason if is_trigger else None,
                reasons=[trigger_reason] if is_trigger else [],
            )
        )
    return RepairAssessment(
        hard_avoid=True,
        hard_avoid_reason=reason,
        pills=[str(bucket["pill"])],
        cosmetic_panels=0,
        glass_cost=0,
        replacement_cost=0,
        risk_buffer=0,
        base_cost=hard_cost,
        severity_level=severity_level,
        severity_multiplier=severity_multiplier,
        total_cost=hard_cost,
        total_cost_low=int(hard_cost * REPAIR_COST_LOW_MULTIPLIER),
        total_cost_high=int(hard_cost * REPAIR_COST_HIGH_MULTIPLIER),
        reasons=[trigger_reason],
        original_text=original_text,
        fragments=fragments,
    )


@lru_cache(maxsize=1)
def _load_v2_entries() -> tuple[V2ConditionEntry, ...]:
    if not V2_DICTIONARY_PATH.exists():
        return ()
    data = yaml.safe_load(V2_DICTIONARY_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return ()
    entries = data.get("entries", [])
    if not isinstance(entries, list):
        return ()
    parsed: list[V2ConditionEntry] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        canonical_defect = str(entry.get("canonical_defect") or entry.get("raw_phrase") or "").strip()
        category = str(entry.get("category") or "").strip().lower()
        severity_hint = str(entry.get("severity_hint") or "").strip().lower()
        pattern_text = str(entry.get("pattern") or "").strip()
        raw_phrase = str(entry.get("raw_phrase") or "").strip()
        if not canonical_defect or not category:
            continue
        if pattern_text:
            pattern_source = pattern_text
        elif raw_phrase:
            pattern_source = rf"\b{re.escape(raw_phrase)}\b"
        else:
            continue
        try:
            pattern = re.compile(pattern_source, re.IGNORECASE)
        except re.error:
            continue
        parsed.append(
            V2ConditionEntry(
                canonical_defect=canonical_defect,
                category=category,
                severity_hint=severity_hint,
                pattern=pattern,
            )
        )
    return tuple(parsed)


def _match_v2_entries(lines: List[str]) -> list[tuple[str, list[V2ConditionEntry]]]:
    entries = _load_v2_entries()
    if not entries:
        return []
    grouped: list[tuple[str, list[V2ConditionEntry]]] = []
    for line in lines:
        hits: list[V2ConditionEntry] = []
        seen: set[str] = set()
        for entry in entries:
            if entry.pattern.search(line) and entry.canonical_defect not in seen:
                hits.append(entry)
                seen.add(entry.canonical_defect)
        if hits:
            grouped.append((line, hits))
    return grouped


def _panel_equivalent_for_line(line: str) -> int:
    lowered = line.lower()
    if "around vehicle" in lowered or "some places" in lowered or "various panels" in lowered:
        return PANEL_CAP
    count = estimate_component_count(lowered)
    comma_count = lowered.count(",") + (1 if "," in lowered else 0)
    if comma_count:
        count = max(count, comma_count)
    location_hits = 0
    for term in PANEL_LOCATION_TERMS:
        location_hits += len(re.findall(rf"\b{re.escape(term)}s?\b", lowered))
    if location_hits:
        count = max(count, location_hits)
    if "both" in lowered:
        count = max(count, 2)
    return max(1, min(PANEL_CAP, count))


def _infer_replacement_canonicals(line: str) -> list[str]:
    lowered = line.lower()
    if not DAMAGE_WORD_RE.search(lowered) or not REPLACEMENT_TARGET_RE.search(lowered):
        return []
    inferred: list[str] = []
    if re.search(r"\b(bumper|bar)\b", lowered):
        inferred.append("bumper_damage")
    if re.search(r"\b(headlight|head light|mirror)\b", lowered):
        inferred.append("mirror_light_damage")
    if re.search(r"\b(tail light|taillight|indicator)\b", lowered):
        inferred.append("lighting_damage")
    return inferred


def _unclassified_fragments(lines: List[str], matched_lines: set[str]) -> list[RepairFragment]:
    fragments: list[RepairFragment] = []
    for line in lines:
        if line in matched_lines:
            continue
        fragments.append(
            RepairFragment(
                original_text=line,
                normalized_text=_fragment_key(line),
                status="unclassified",
                category="unclassified",
            )
        )
    return fragments


class ConditionDictionary:
    def __init__(self, csv_path: str):
        self.map: Dict[str, Dict[str, object]] = {}
        try:
            df = pd.read_csv(csv_path).fillna("")
        except FileNotFoundError:
            return
        for _, row in df.iterrows():
            raw_line = normalise_condition_line(str(row.get("raw_line", "")))
            if not raw_line.strip(".").strip():
                continue
            self.map[raw_line] = {
                "group": str(row.get("group", "")).strip(),
                "panel_equiv": int(row.get("panel_equiv", 0) or 0),
                "fixed_cost": int(row.get("fixed_cost", 0) or 0),
                "auto_avoid": int(row.get("auto_avoid", 0) or 0),
                "canonical_key": str(row.get("canonical_key", "")).strip(),
            }

    def lookup(self, line: str) -> Optional[Dict[str, object]]:
        return self.map.get(normalise_condition_line(line))


def assess_repairs(
    general_condition: str,
    dict_csv_path: str = "condition_dictionary.csv",
    adas_windscreen: bool = False,
    extra_risk_flags: Optional[List[str]] = None,
    vehicle_value: Optional[float] = None,
) -> RepairAssessment:
    cosmetic_only_cap = HARD_CAPS["cosmetic_only"]
    if vehicle_value and vehicle_value > 0:
        cosmetic_only_cap = min(cosmetic_only_cap, vehicle_value * COSMETIC_CAP_PCT_OF_VALUE)
    feature_set = build_repair_features(general_condition)
    severity_level = feature_set.severity_level or "minor"
    severity_multiplier = float(SEVERITY_MULTIPLIERS.get(severity_level, 1.0))
    lines = split_condition_lines(general_condition)

    mechanical_trigger = _mechanical_trigger_line(lines)
    if mechanical_trigger:
        return _hard_avoid_assessment(
            "mechanical",
            severity_level=severity_level,
            severity_multiplier=severity_multiplier,
            trigger_reason="MECHANICAL_REGEX_HIT",
            original_text=str(general_condition or ""),
            lines=lines,
            trigger_line=mechanical_trigger,
        )

    grouped_v2_hits = _match_v2_entries(lines)
    if grouped_v2_hits:
        pills: set[str] = set()
        reasons: List[str] = []
        cosmetic_panels = 0
        glass_cost = 0
        replacement_cost = 0
        risk_buffer = 0
        uncapped_structural_cost = 0
        has_glass = False
        has_replacement = False
        has_unknown = False
        fragments: list[RepairFragment] = []
        matched_lines: set[str] = set()

        for line, hits in grouped_v2_hits:
            matched_lines.add(line)
            canonicals = {hit.canonical_defect for hit in hits}
            categories = {hit.category for hit in hits}
            if "replacement_required" in canonicals and any(
                hit.category == "replacement" and hit.canonical_defect != "replacement_required"
                for hit in hits
            ):
                canonicals.discard("replacement_required")
            line_pills: set[str] = set()
            line_reasons: list[str] = []
            line_cost = 0
            line_category = "matched"

            hard_avoid_hit = sorted(canonicals.intersection(V2_HARD_AVOID_CANONICALS))
            if hard_avoid_hit:
                return _hard_avoid_assessment(
                    "mechanical",
                    severity_level=severity_level,
                    severity_multiplier=severity_multiplier,
                    trigger_reason=f"V2_AVOID: {hard_avoid_hit[0]}: {line}",
                    original_text=str(general_condition or ""),
                    lines=lines,
                    trigger_line=line,
                )

            structural_hard_avoid_hit = sorted(canonicals.intersection(STRUCTURAL_HARD_AVOID_CANONICALS))
            if structural_hard_avoid_hit:
                return _hard_avoid_assessment(
                    "structural",
                    severity_level=severity_level,
                    severity_multiplier=severity_multiplier,
                    trigger_reason=f"V2_AVOID: {structural_hard_avoid_hit[0]}: {line}",
                    original_text=str(general_condition or ""),
                    lines=lines,
                    trigger_line=line,
                )

            if canonicals.intersection(V2_UNKNOWN_CANONICALS):
                pills.add("UNKNOWN")
                line_pills.add("UNKNOWN")
                line_category = "boilerplate"
                if not has_unknown:
                    risk_buffer += RISK_BUFFERS["unknown_photos"]
                    line_cost += RISK_BUFFERS["unknown_photos"]
                    has_unknown = True
                reason = f"V2_UNKNOWN: {line}"
                reasons.append(reason)
                line_reasons.append(reason)

            if canonicals.intersection(V2_GLASS_CANONICALS) or "glass" in categories:
                pills.add("GLASS")
                line_pills.add("GLASS")
                line_category = "glass"
                has_glass = True
                if "window_damage" in canonicals and "windscreen_damage" not in canonicals:
                    current_cost = _effective_cost("window_damage", WINDSCREEN_STD)
                elif "window_tint_damage" in canonicals and "windscreen_damage" not in canonicals:
                    current_cost = _effective_cost("window_tint_damage", WINDSCREEN_STD)
                else:
                    current_cost = _windscreen_glass_cost(adas_windscreen)
                glass_cost += current_cost
                line_cost += current_cost
                reason = f"V2_GLASS: {line}"
                reasons.append(reason)
                line_reasons.append(reason)

            if "structural_damage" in canonicals or "hail_damage" in canonicals or "structural" in categories:
                pills.add("PANEL_REPLACE")
                line_pills.add("PANEL_REPLACE")
                line_category = "structural"
                has_replacement = True
                panel_count = max(2, _panel_equivalent_for_line(line))
                _structural_key = "hail_damage" if "hail_damage" in canonicals and "structural_damage" not in canonicals else "structural_damage"
                # Hail/structural repair scales with panel count and can far exceed the
                # cosmetic caps (schedule high end for hail is ~$10k), so this component
                # bypasses HARD_CAPS instead of being flattened to the $1,500 ceiling.
                current_cost = _effective_cost(_structural_key, 900) + panel_count * PANEL_RATE
                uncapped_structural_cost += current_cost
                line_cost += current_cost
                reason = f"V2_STRUCTURAL: {line}"
                reasons.append(reason)
                line_reasons.append(reason)
                fragments.append(
                    RepairFragment(
                        original_text=line,
                        normalized_text=_fragment_key(line),
                        status="matched",
                        category=line_category,
                        canonical_defects=sorted(canonicals),
                        pills=sorted(line_pills),
                        cost_estimate=int(round(line_cost * severity_multiplier)),
                        reasons=line_reasons,
                    )
                )
                continue

            replacement_hits = [
                hit for hit in hits if hit.category == "replacement" or hit.canonical_defect == "battery_issue"
            ]
            if any(hit.canonical_defect != "replacement_required" for hit in replacement_hits):
                replacement_hits = [
                    hit for hit in replacement_hits if hit.canonical_defect != "replacement_required"
                ]
            if not replacement_hits:
                inferred_replacements = _infer_replacement_canonicals(line)
                for canonical in inferred_replacements:
                    replacement_hits.append(
                        V2ConditionEntry(
                            canonical_defect=canonical,
                            category="replacement",
                            severity_hint="medium",
                            pattern=REPLACEMENT_TARGET_RE,
                        )
                    )
            if replacement_hits:
                pills.add("PANEL_REPLACE")
                line_pills.add("PANEL_REPLACE")
                line_category = "replacement"
                has_replacement = True
                for hit in replacement_hits:
                    current_cost = _effective_cost(hit.canonical_defect, 600)
                    replacement_cost += current_cost
                    line_cost += current_cost
                    reason = f"V2_REPLACEMENT:{hit.canonical_defect}: {line}"
                    reasons.append(reason)
                    line_reasons.append(reason)

            interior_hits = [hit for hit in hits if hit.category == "interior"]
            if interior_hits:
                line_category = "interior"
                if any(hit.canonical_defect == "seat_damage" for hit in interior_hits):
                    interior_hits = [hit for hit in interior_hits if hit.canonical_defect != "seat_issue"]
                for hit in interior_hits:
                    current_cost = _effective_cost(hit.canonical_defect, 200)
                    replacement_cost += current_cost
                    line_cost += current_cost
                    reason = f"V2_INTERIOR:{hit.canonical_defect}: {line}"
                    reasons.append(reason)
                    line_reasons.append(reason)

            if "corrosion_damage" in canonicals:
                # Rust repair is body-shop work quoted around $1,000-$1,200 for
                # panel/sill surface rust, not a $300 panel polish -- price it from
                # the schedule and let it use the with_replacement cap tier.
                pills.add("PANEL_REPLACE")
                line_pills.add("PANEL_REPLACE")
                if line_category == "matched":
                    line_category = "cosmetic"
                has_replacement = True
                current_cost = _effective_cost("corrosion_damage", 1200)
                replacement_cost += current_cost
                line_cost += current_cost
                reason = f"V2_CORROSION: {line}"
                reasons.append(reason)
                line_reasons.append(reason)

            cosmetic_hits = [
                hit
                for hit in hits
                if hit.category == "cosmetic"
                and hit.canonical_defect not in {"body_location_list", "corrosion_damage"}
            ]
            if replacement_hits or "interior" in categories:
                cosmetic_hits = [hit for hit in cosmetic_hits if hit.canonical_defect != "generic_damage"]
            if cosmetic_hits and "glass" not in categories:
                pills.add("COSMETIC_PANEL")
                line_pills.add("COSMETIC_PANEL")
                if line_category == "matched":
                    line_category = "cosmetic"
                panel_count = _panel_equivalent_for_line(line)
                cosmetic_panels += panel_count
                line_cost += panel_count * PANEL_RATE
                reason = f"V2_COSMETIC: {line}"
                reasons.append(reason)
                line_reasons.append(reason)

            fragments.append(
                RepairFragment(
                    original_text=line,
                    normalized_text=_fragment_key(line),
                    status=(
                        "ignored"
                        if (line_category == "boilerplate" or categories == {"boilerplate"}) and line_cost == 0
                        else "matched"
                        if line_reasons
                        else "unclassified"
                    ),
                    category=(
                        "boilerplate"
                        if (line_category == "boilerplate" or categories == {"boilerplate"}) and line_cost == 0
                        else line_category
                        if line_reasons
                        else "unclassified"
                    ),
                    canonical_defects=sorted(canonicals),
                    pills=sorted(line_pills),
                    cost_estimate=int(round(line_cost * severity_multiplier)),
                    reasons=line_reasons,
                )
            )

        cosmetic_panels = min(cosmetic_panels, PANEL_CAP)
        cosmetic_cost = cosmetic_panels * PANEL_RATE
        base_total = cosmetic_cost + glass_cost + replacement_cost + risk_buffer

        if has_replacement:
            base_total = min(base_total, HARD_CAPS["with_replacement"])
        elif has_glass:
            base_total = min(base_total, HARD_CAPS["cosmetic_plus_glass"])
        else:
            base_total = min(base_total, cosmetic_only_cap)

        # Hail/structural repair sits outside the cosmetic cap tiers.
        base_total += uncapped_structural_cost

        if extra_risk_flags:
            for flag in extra_risk_flags:
                base_total += RISK_BUFFERS.get(flag, 0)

        total = int(round(base_total * severity_multiplier))
        return RepairAssessment(
            hard_avoid=False,
            hard_avoid_reason=None,
            pills=sorted(pills),
            cosmetic_panels=cosmetic_panels,
            glass_cost=glass_cost,
            replacement_cost=replacement_cost,
            risk_buffer=risk_buffer,
            base_cost=int(base_total),
            severity_level=severity_level,
            severity_multiplier=severity_multiplier,
            total_cost=total,
            total_cost_low=int(total * REPAIR_COST_LOW_MULTIPLIER),
            total_cost_high=int(total * REPAIR_COST_HIGH_MULTIPLIER),
            reasons=reasons,
            original_text=str(general_condition or ""),
            fragments=fragments + _unclassified_fragments(lines, matched_lines),
        )

    cd = ConditionDictionary(dict_csv_path)

    pills: set[str] = set()
    reasons: List[str] = []
    cosmetic_panels = 0
    glass_cost = 0
    replacement_cost = 0
    risk_buffer = 0
    has_glass = False
    has_replacement = False
    fragments: list[RepairFragment] = []
    matched_lines: set[str] = set()

    for line in lines:
        hit = cd.lookup(line)
        if not hit:
            continue
        matched_lines.add(line)

        group = str(hit.get("group", "")).strip()
        if hit.get("auto_avoid", 0) == 1 or group == "MECHANICAL":
            return _hard_avoid_assessment(
                "mechanical",
                severity_level=severity_level,
                severity_multiplier=severity_multiplier,
                trigger_reason=f"DICT_AVOID: {line}",
                original_text=str(general_condition or ""),
                lines=lines,
                trigger_line=line,
            )

        if group:
            pills.add(group)
            reasons.append(f"DICT_{group}: {line}")

        if group == "COSMETIC_PANEL":
            cosmetic_panels += int(hit.get("panel_equiv", 1) or 1)

        if group == "GLASS":
            has_glass = True
            fixed_cost = int(hit.get("fixed_cost", 0) or 0)
            glass_cost += fixed_cost if fixed_cost > 0 else _windscreen_glass_cost(adas_windscreen)

        if group == "PANEL_REPLACE":
            has_replacement = True
            replacement_cost += int(hit.get("fixed_cost", 0) or 600)

        if group == "UNKNOWN":
            risk_buffer += RISK_BUFFERS["unknown_photos"]
        fragments.append(
            RepairFragment(
                original_text=line,
                normalized_text=_fragment_key(line),
                status="matched",
                category=group or "matched",
                canonical_defects=[str(hit.get("canonical_key", "")).strip()] if hit.get("canonical_key") else [],
                pills=[group] if group else [],
                cost_estimate=int(hit.get("fixed_cost", 0) or 0),
                reasons=[f"DICT_{group}: {line}"] if group else [],
            )
        )

    for line in lines:
        lower = line.lower()
        fallback_pills: set[str] = set()
        fallback_reasons: list[str] = []
        fallback_cost = 0
        fallback_category = ""
        if "dents or marks on body consistent with age" in lower:
            pills.add("COSMETIC_PANEL")
            fallback_pills.add("COSMETIC_PANEL")
            cosmetic_panels += 1
            fallback_cost += PANEL_RATE
            fallback_category = "cosmetic"
            reason = f"FALLBACK_COSMETIC: {line}"
            reasons.append(reason)
            fallback_reasons.append(reason)
        if "windscreen" in lower and ("chipped" in lower or "cracked" in lower):
            pills.add("GLASS")
            fallback_pills.add("GLASS")
            has_glass = True
            current_cost = _windscreen_glass_cost(adas_windscreen)
            glass_cost += current_cost
            fallback_cost += current_cost
            fallback_category = "glass"
            reason = f"FALLBACK_GLASS: {line}"
            reasons.append(reason)
            fallback_reasons.append(reason)
        if "please refer to the photos" in lower or "arrange inspection" in lower:
            pills.add("UNKNOWN")
            fallback_pills.add("UNKNOWN")
            risk_buffer += RISK_BUFFERS["unknown_photos"]
            fallback_cost += RISK_BUFFERS["unknown_photos"]
            fallback_category = fallback_category or "boilerplate"
            reason = f"FALLBACK_UNKNOWN: {line}"
            reasons.append(reason)
            fallback_reasons.append(reason)
        if fallback_reasons and line not in matched_lines:
            matched_lines.add(line)
            fragments.append(
                RepairFragment(
                    original_text=line,
                    normalized_text=_fragment_key(line),
                    status="matched",
                    category=fallback_category or "matched",
                    pills=sorted(fallback_pills),
                    cost_estimate=int(round(fallback_cost * severity_multiplier)),
                    reasons=fallback_reasons,
                )
            )

    cosmetic_panels = min(cosmetic_panels, PANEL_CAP)
    cosmetic_cost = cosmetic_panels * PANEL_RATE
    base_total = cosmetic_cost + glass_cost + replacement_cost + risk_buffer

    if has_replacement:
        base_total = min(base_total, HARD_CAPS["with_replacement"])
    elif has_glass:
        base_total = min(base_total, HARD_CAPS["cosmetic_plus_glass"])
    else:
        base_total = min(base_total, cosmetic_only_cap)

    if extra_risk_flags:
        for flag in extra_risk_flags:
            base_total += RISK_BUFFERS.get(flag, 0)

    total = int(round(base_total * severity_multiplier))

    return RepairAssessment(
        hard_avoid=False,
        hard_avoid_reason=None,
        pills=sorted(pills),
        cosmetic_panels=cosmetic_panels,
        glass_cost=glass_cost,
        replacement_cost=replacement_cost,
        risk_buffer=risk_buffer,
        base_cost=int(base_total),
        severity_level=severity_level,
        severity_multiplier=severity_multiplier,
        total_cost=total,
        total_cost_low=int(total * REPAIR_COST_LOW_MULTIPLIER),
        total_cost_high=int(total * REPAIR_COST_HIGH_MULTIPLIER),
        reasons=reasons,
        original_text=str(general_condition or ""),
        fragments=fragments + _unclassified_fragments(lines, matched_lines),
    )


def apply_repairs_to_max_bid(
    max_bid: int,
    assessment: RepairAssessment,
    vehicle_value: Optional[float] = None,
) -> Tuple[int, str]:
    if assessment.hard_avoid:
        return 0, "Avoid"

    # Deduct the HIGH (pessimistic) estimate from the max bid to stay conservative.
    deduct = assessment.total_cost_high if assessment.total_cost_high > 0 else assessment.total_cost
    adjusted = max(0, int(max_bid) - deduct)

    # Verdict is based on the DEFAULT estimate so the label reflects the likely scenario.
    # Gates scale with vehicle_value when known -- see _repair_gate_thresholds.
    good_max, marginal_max, not_viable_max = _repair_gate_thresholds(vehicle_value)
    if assessment.total_cost <= good_max:
        verdict = "Good"
    elif assessment.total_cost <= marginal_max:
        verdict = "Marginal"
    elif assessment.total_cost <= not_viable_max:
        verdict = "Not Viable"
    else:
        verdict = "Avoid"

    return adjusted, verdict


def repair_decision_label(assessment: RepairAssessment, vehicle_value: Optional[float] = None) -> str:
    if assessment.hard_avoid:
        reason = (assessment.hard_avoid_reason or "condition").replace("_", " ")
        return f"HARD AVOID ({reason})"
    good_max, marginal_max, not_viable_max = _repair_gate_thresholds(vehicle_value)
    if assessment.total_cost <= good_max:
        return "GOOD (repairs)"
    if assessment.total_cost <= marginal_max:
        return "MARGINAL (repairs)"
    if assessment.total_cost <= not_viable_max:
        return "NOT VIABLE (repairs)"
    return "AVOID (repairs)"


def repair_fragments_to_records(assessment: RepairAssessment) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for fragment in assessment.fragments:
        records.append(
            {
                "original_text": fragment.original_text,
                "repair_key": fragment.normalized_text,
                "status": fragment.status,
                "category": fragment.category,
                "canonical_defects": "|".join(fragment.canonical_defects),
                "pills": "|".join(fragment.pills),
                "cost_estimate": fragment.cost_estimate,
                "hard_avoid_reason": fragment.hard_avoid_reason or "",
                "reasons": " | ".join(fragment.reasons),
            }
        )
    return records


def serialize_repair_fragments(assessment: RepairAssessment) -> str:
    return json.dumps(repair_fragments_to_records(assessment), ensure_ascii=False)
