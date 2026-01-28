"""Repair pricing and hard-avoid logic for auction condition notes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import re

import pandas as pd


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
    total_cost: int
    reasons: List[str]


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
    lines = split_condition_lines(general_condition)

    if any_mechanical(lines):
        return RepairAssessment(
            hard_avoid=True,
            pills=["MECHANICAL"],
            cosmetic_panels=0,
            glass_cost=0,
            replacement_cost=0,
            risk_buffer=0,
            total_cost=10000,
            reasons=["MECHANICAL_REGEX_HIT"],
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
            return RepairAssessment(
                hard_avoid=True,
                pills=["MECHANICAL"],
                cosmetic_panels=0,
                glass_cost=0,
                replacement_cost=0,
                risk_buffer=0,
                total_cost=10000,
                reasons=[f"DICT_AVOID: {line}"],
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
    total = cosmetic_cost + glass_cost + replacement_cost + risk_buffer

    if has_replacement:
        total = min(total, HARD_CAPS["with_replacement"])
    elif has_glass:
        total = min(total, HARD_CAPS["cosmetic_plus_glass"])
    else:
        total = min(total, HARD_CAPS["cosmetic_only"])

    if extra_risk_flags:
        for flag in extra_risk_flags:
            total += RISK_BUFFERS.get(flag, 0)

    return RepairAssessment(
        hard_avoid=False,
        pills=sorted(pills),
        cosmetic_panels=cosmetic_panels,
        glass_cost=glass_cost,
        replacement_cost=replacement_cost,
        risk_buffer=risk_buffer,
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
