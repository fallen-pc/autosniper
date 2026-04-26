"""Repair pricing and hard-avoid logic for auction condition notes."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple
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
    "battery_issue": 300,
    "control_damage": 250,
    "seat_damage": 250,
    "seat_issue": 150,
    "interior_trim_damage": 250,
    "structural_damage": 900,
    "hail_damage": 900,
}

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

DAMAGE_WORD_RE = re.compile(r"\b(crack|cracked|broken|missing|damaged|damage|torn|chip|chipped)\b", re.IGNORECASE)
REPLACEMENT_TARGET_RE = re.compile(
    r"\b(headlight|head light|tail light|taillight|indicator|mirror|bumper|bar)\b",
    re.IGNORECASE,
)

MECH_AVOID_PATTERNS = [
    r"\bengine (light|warning) on\b",
    r"\bother warning light on\b",
    r"\babs light on\b",
    r"\bairbag light on\b",
    r"\btraction control light on\b",
    r"\bcheck engine\b",
    r"\bengine noise\b",
    r"\btransmission\b.*\b(attention|fault|issue|noise|slip)\b",
    r"\bgearbox\b.*\b(attention|fault|issue|noise|slip)\b",
    r"\boverheating\b",
    r"\bcooling\b.*\b(leak|issue|fault)\b",
    r"\boil leak\b",
    r"\bpower steering\b.*\b(fault|issue|leak)\b",
    r"\bdrivetrain\b.*\b(fault|issue)\b",
    r"\bsuspension\b.*\b(fault|issue|noise)\b",
    r"\balignment\b.*\b(issue|pull)\b",
    r"\bbrake\b.*\b(fault|issue)\b",
    r"\bdoes not start\b",
    r"\bwon't start\b",
    r"\bnot running\b",
]

MECH_AVOID_RE = [re.compile(pattern, re.IGNORECASE) for pattern in MECH_AVOID_PATTERNS]


def normalise_condition_line(line: str) -> str:
    text = (line or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text.rstrip(" .") + "." if text else ""


def split_condition_lines(text: str) -> List[str]:
    if not text:
        return []
    parts = re.split(r"[\r\n]+", str(text))
    out: List[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        out.append(normalise_condition_line(part))
    seen = set()
    deduped: List[str] = []
    for line in out:
        if line not in seen:
            seen.add(line)
            deduped.append(line)
    return deduped


@dataclass(frozen=True)
class V2ConditionEntry:
    canonical_defect: str
    category: str
    severity_hint: str
    pattern: re.Pattern[str]


def any_mechanical(lines: List[str]) -> bool:
    for line in lines:
        for regex in MECH_AVOID_RE:
            if regex.search(line):
                return True
    return False


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


HARD_AVOID_BUCKETS = {
    "mechanical": {"pill": "MECHANICAL", "cost": 10_000},
    "structural": {"pill": "STRUCTURAL", "cost": 8_000},
    "unknown": {"pill": "UNKNOWN", "cost": 4_000},
}


def _hard_avoid_assessment(
    reason: str,
    *,
    severity_level: str,
    severity_multiplier: float,
    trigger_reason: str,
) -> RepairAssessment:
    bucket = HARD_AVOID_BUCKETS.get(reason, HARD_AVOID_BUCKETS["mechanical"])
    hard_cost = int(bucket["cost"])
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
        reasons=[trigger_reason],
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
) -> RepairAssessment:
    feature_set = build_repair_features(general_condition)
    severity_level = feature_set.severity_level or "minor"
    severity_multiplier = float(SEVERITY_MULTIPLIERS.get(severity_level, 1.0))
    lines = split_condition_lines(general_condition)

    if any_mechanical(lines):
        return _hard_avoid_assessment(
            "mechanical",
            severity_level=severity_level,
            severity_multiplier=severity_multiplier,
            trigger_reason="MECHANICAL_REGEX_HIT",
        )

    grouped_v2_hits = _match_v2_entries(lines)
    if grouped_v2_hits:
        pills: set[str] = set()
        reasons: List[str] = []
        cosmetic_panels = 0
        glass_cost = 0
        replacement_cost = 0
        risk_buffer = 0
        has_glass = False
        has_replacement = False

        for line, hits in grouped_v2_hits:
            canonicals = {hit.canonical_defect for hit in hits}
            categories = {hit.category for hit in hits}

            hard_avoid_hit = sorted(canonicals.intersection(V2_HARD_AVOID_CANONICALS))
            if hard_avoid_hit:
                return _hard_avoid_assessment(
                    "mechanical",
                    severity_level=severity_level,
                    severity_multiplier=severity_multiplier,
                    trigger_reason=f"V2_AVOID: {hard_avoid_hit[0]}: {line}",
                )

            structural_hard_avoid_hit = sorted(canonicals.intersection(STRUCTURAL_HARD_AVOID_CANONICALS))
            if structural_hard_avoid_hit:
                return _hard_avoid_assessment(
                    "structural",
                    severity_level=severity_level,
                    severity_multiplier=severity_multiplier,
                    trigger_reason=f"V2_AVOID: {structural_hard_avoid_hit[0]}: {line}",
                )

            if canonicals.intersection(V2_UNKNOWN_CANONICALS):
                pills.add("UNKNOWN")
                risk_buffer += RISK_BUFFERS["unknown_photos"]
                reasons.append(f"V2_UNKNOWN: {line}")

            if canonicals.intersection(V2_GLASS_CANONICALS) or "glass" in categories:
                pills.add("GLASS")
                has_glass = True
                glass_cost += WINDSCREEN_ADAS if adas_windscreen else WINDSCREEN_STD
                reasons.append(f"V2_GLASS: {line}")

            if "structural_damage" in canonicals or "hail_damage" in canonicals or "structural" in categories:
                pills.add("PANEL_REPLACE")
                has_replacement = True
                cosmetic_panels += max(2, _panel_equivalent_for_line(line))
                replacement_cost += V2_REPLACEMENT_COSTS.get("structural_damage", 900)
                reasons.append(f"V2_STRUCTURAL: {line}")
                continue

            replacement_hits = [
                hit for hit in hits if hit.category == "replacement" or hit.canonical_defect == "battery_issue"
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
                has_replacement = True
                for hit in replacement_hits:
                    replacement_cost += int(V2_REPLACEMENT_COSTS.get(hit.canonical_defect, 600))
                    reasons.append(f"V2_REPLACEMENT:{hit.canonical_defect}: {line}")

            interior_hits = [hit for hit in hits if hit.category == "interior"]
            if interior_hits:
                for hit in interior_hits:
                    replacement_cost += int(V2_REPLACEMENT_COSTS.get(hit.canonical_defect, 200))
                    reasons.append(f"V2_INTERIOR:{hit.canonical_defect}: {line}")

            cosmetic_hits = [
                hit
                for hit in hits
                if hit.category == "cosmetic" and hit.canonical_defect not in {"body_location_list"}
            ]
            if cosmetic_hits and not replacement_hits and "glass" not in categories:
                pills.add("COSMETIC_PANEL")
                cosmetic_panels += _panel_equivalent_for_line(line)
                reasons.append(f"V2_COSMETIC: {line}")

        cosmetic_panels = min(cosmetic_panels, PANEL_CAP)
        cosmetic_cost = cosmetic_panels * PANEL_RATE
        base_total = cosmetic_cost + glass_cost + replacement_cost + risk_buffer

        if has_replacement:
            base_total = min(base_total, HARD_CAPS["with_replacement"])
        elif has_glass:
            base_total = min(base_total, HARD_CAPS["cosmetic_plus_glass"])
        else:
            base_total = min(base_total, HARD_CAPS["cosmetic_only"])

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
            reasons=reasons,
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

    for line in lines:
        hit = cd.lookup(line)
        if not hit:
            continue

        group = str(hit.get("group", "")).strip()
        if hit.get("auto_avoid", 0) == 1 or group == "MECHANICAL":
            return _hard_avoid_assessment(
                "mechanical",
                severity_level=severity_level,
                severity_multiplier=severity_multiplier,
                trigger_reason=f"DICT_AVOID: {line}",
            )

        if group:
            pills.add(group)
            reasons.append(f"DICT_{group}: {line}")

        if group == "COSMETIC_PANEL":
            cosmetic_panels += int(hit.get("panel_equiv", 1) or 1)

        if group == "GLASS":
            has_glass = True
            fixed_cost = int(hit.get("fixed_cost", 0) or 0)
            glass_cost += fixed_cost if fixed_cost > 0 else (
                WINDSCREEN_ADAS if adas_windscreen else WINDSCREEN_STD
            )

        if group == "PANEL_REPLACE":
            has_replacement = True
            replacement_cost += int(hit.get("fixed_cost", 0) or 600)

        if group == "UNKNOWN":
            risk_buffer += RISK_BUFFERS["unknown_photos"]

    for line in lines:
        lower = line.lower()
        if "dents or marks on body consistent with age" in lower:
            pills.add("COSMETIC_PANEL")
            cosmetic_panels += 1
            reasons.append(f"FALLBACK_COSMETIC: {line}")
        if "windscreen" in lower and ("chipped" in lower or "cracked" in lower):
            pills.add("GLASS")
            has_glass = True
            glass_cost += WINDSCREEN_ADAS if adas_windscreen else WINDSCREEN_STD
            reasons.append(f"FALLBACK_GLASS: {line}")
        if "please refer to the photos" in lower or "arrange inspection" in lower:
            pills.add("UNKNOWN")
            risk_buffer += RISK_BUFFERS["unknown_photos"]
            reasons.append(f"FALLBACK_UNKNOWN: {line}")

    cosmetic_panels = min(cosmetic_panels, PANEL_CAP)
    cosmetic_cost = cosmetic_panels * PANEL_RATE
    base_total = cosmetic_cost + glass_cost + replacement_cost + risk_buffer

    if has_replacement:
        base_total = min(base_total, HARD_CAPS["with_replacement"])
    elif has_glass:
        base_total = min(base_total, HARD_CAPS["cosmetic_plus_glass"])
    else:
        base_total = min(base_total, HARD_CAPS["cosmetic_only"])

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
        reasons=reasons,
    )


def apply_repairs_to_max_bid(max_bid: int, assessment: RepairAssessment) -> Tuple[int, str]:
    if assessment.hard_avoid:
        return 0, "Avoid"

    adjusted = max(0, int(max_bid) - int(assessment.total_cost))

    if assessment.total_cost <= 600:
        verdict = "Good"
    elif assessment.total_cost <= 1000:
        verdict = "Marginal"
    elif assessment.total_cost <= 1500:
        verdict = "Not Viable"
    else:
        verdict = "Avoid"

    return adjusted, verdict
