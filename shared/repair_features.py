"""Helpers for transforming general condition text into structured repair features."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Iterable, List, Sequence, Set


REPAIR_CATEGORIES: dict[str, Sequence[str]] = {
    "engine_mechanical": (
        "engine",
        "gearbox",
        "transmission",
        "clutch",
        "oil leak",
        "oil leak",
        "overheat",
        "overheating",
        "engine noise observed",
        "engine idling rough",
        "knock",
        "mechanical",
        "drivetrain",
        "diff",
    ),
    "electrical": (
        "electrical",
        "warning light",
        "abs",
        "airbag",
        "battery",
        "alternator",
        "ecu",
        "wiring",
        "sensor",
    ),
    "non_operational": (
        "does not start",
        "doesn't start",
        "not running",
        "inoperative",
        "won't start",
        "not start",
        "no start",
    ),
    "suspension_brakes": (
        "suspension",
        "brake",
        "steering",
        "alignment",
        "bearing",
        "shock",
        "strut",
    ),
    "interior": (
        "interior",
        "seat",
        "trim",
        "lining",
        "dashboard",
        "dash",
        "stain",
        "carpet",
    ),
    "body_exterior": (
        "scratch",
        "dent",
        "paint",
        "hail",
        "rust",
        "panel",
        "bumper",
        "guard",
        "windscreen",
        "glass",
    ),
    "tyres_wheels": (
        "tyre",
        "tire",
        "wheel",
        "rim",
        "spare",
    ),
    "general_wear": (
        "wear",
        "tear",
        "age related",
        "used condition",
        "consistent with age",
        "general condition",
    ),
    "unknown_untested": (
        "not tested",
        "condition unknown",
        "as is",
        "unknown condition",
        "no guarantee",
    ),
}

SEVERITY_WEIGHTS: dict[str, int] = {
    "engine_mechanical": 40,
    "electrical": 30,
    "non_operational": 50,
    "suspension_brakes": 20,
    "interior": 10,
    "body_exterior": 5,
    "tyres_wheels": 3,
    "general_wear": 1,
    "unknown_untested": 15,
}

FLUFF_PHRASES: tuple[str, ...] = (
    "consistent with age",
    "consistent with kilometres",
    "consistent with kilometers",
    "consistent with km",
    "general wear and tear",
    "general wear & tear",
    "sold as is",
    "condition unknown",
    "not tested",
    "no warranty",
    "please refer to the photos",
    "refer to the photos",
    "arrange inspection",
)

SPLIT_PATTERN = re.compile(r"[.;\n]+")
WHITESPACE_RE = re.compile(r"\s+")
NON_WORD_RE = re.compile(r"[^a-z0-9\s]+")


@dataclass
class RepairFeatureSet:
    """Structured repair features extracted from the free-text note."""

    normalized_text: str
    clean_text: str
    defects_only: str
    tags: list[str]
    severity: int
    decision_label: str


def normalize_condition_text(text: str) -> str:
    """Collapse whitespace/newlines to produce a single-line summary."""
    cleaned = WHITESPACE_RE.sub(" ", text or "").strip()
    return cleaned


def strip_fluff_phrases(text: str) -> str:
    """Remove boilerplate or low-signal phrases from the condition text."""
    lowered = text
    for phrase in FLUFF_PHRASES:
        lowered = re.sub(re.escape(phrase), "", lowered, flags=re.IGNORECASE)
    lowered = re.sub(r"\s{2,}", " ", lowered).strip()
    return lowered


def _sentence_fragments(text: str) -> list[str]:
    fragments = []
    for chunk in SPLIT_PATTERN.split(text):
        chunk = chunk.strip(" -")
        if not chunk:
            continue
        fragments.append(chunk)
    return fragments


def tag_condition(text: str) -> list[str]:
    """Return the repair categories detected in the provided text."""
    lowered = text.lower()
    detected: list[str] = []
    for category, keywords in REPAIR_CATEGORIES.items():
        if any(keyword in lowered for keyword in keywords):
            detected.append(category)
    return detected


def compute_severity(tags: Iterable[str]) -> int:
    """Sum the configured severity weights for the detected tags."""
    unique_tags: Set[str] = set(tag for tag in tags if tag in SEVERITY_WEIGHTS)
    return sum(SEVERITY_WEIGHTS[tag] for tag in unique_tags)


def defects_only_summary(text: str) -> str:
    """Keep only fragments that appear to reference a real defect."""
    lowered = text.lower()
    keepers: list[str] = []
    fragments = _sentence_fragments(text)

    keywords: Set[str] = set()
    for values in REPAIR_CATEGORIES.values():
        for keyword in values:
            simplified = keyword.replace("'", "").strip()
            if simplified:
                keywords.add(simplified.lower())

    for fragment in fragments:
        fragment_lower = fragment.lower()
        if any(keyword in fragment_lower for keyword in keywords):
            keepers.append(fragment.strip())

    if not keepers:
        return ""
    return "; ".join(keepers)


def decision_from_severity(severity: int) -> str:
    """Translate the numeric severity into a high-level decision label."""
    if severity >= 50:
        return "PARTS ONLY"
    if severity >= 30:
        return "AVOID (condition)"
    if severity <= 15:
        return "BUY (condition)"
    return "REVIEW (condition)"


def build_repair_features(condition_text: str | float | None) -> RepairFeatureSet:
    """Generate the derived repair features for a listing."""
    if condition_text is None or (isinstance(condition_text, float) and not condition_text == condition_text):
        condition_text = ""
    raw = str(condition_text).strip()
    normalized = normalize_condition_text(raw)
    cleaned = strip_fluff_phrases(normalized)
    defects = defects_only_summary(cleaned)
    tags = tag_condition(cleaned)
    severity = compute_severity(tags)
    decision = decision_from_severity(severity)
    return RepairFeatureSet(
        normalized_text=normalized,
        clean_text=cleaned,
        defects_only=defects,
        tags=tags,
        severity=severity,
        decision_label=decision,
    )


def serialize_tags(tags: Sequence[str]) -> str:
    """JSON-serialize the tag list for easy CSV storage."""
    return json.dumps(list(tags), ensure_ascii=False)


def repair_feature_columns() -> list[str]:
    """Column names emitted by build_repair_features."""
    return [
        "general_condition_norm",
        "condition_clean",
        "defects_only",
        "repair_tags",
        "repair_severity",
        "decision_condition_only",
    ]
