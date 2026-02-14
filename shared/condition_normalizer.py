from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple

import yaml
from shared.data_loader import dataset_path

RULES_PATH = Path(__file__).resolve().parent.parent / "config" / "condition_rules_v1.csv"
RULES_V2_PATH = Path(__file__).resolve().parent.parent / "config" / "condition_dictionary_v2.yaml"
SPLIT_RULES_V2_PATH = Path(__file__).resolve().parent.parent / "config" / "condition_split_rules_v2.yaml"

ABBREV_MAP = {
    "lhf": "left hand front",
    "lhr": "left hand rear",
    "rhf": "right hand front",
    "rhr": "right hand rear",
    "lhs": "left hand side",
    "rhs": "right hand side",
    "rego": "registration",
    "odo": "odometer",
    "windscreen": "windscreen",
    "windshield": "windscreen",
}

DEFECT_KEYWORDS = {
    "scratch",
    "scratched",
    "scuff",
    "scuffed",
    "dent",
    "dented",
    "crack",
    "cracked",
    "chip",
    "chipped",
    "broken",
    "missing",
    "rust",
    "corrosion",
    "leak",
    "leaking",
    "warning",
    "overheating",
    "rattle",
    "noise",
    "paint",
    "peeling",
    "fade",
    "fading",
    "tear",
    "torn",
}

LOCATION_WORDS = {
    "roof",
    "bonnet",
    "bootlid",
    "boot",
    "tailgate",
    "door",
    "doors",
    "panel",
    "panels",
    "hood",
    "bumper",
    "bar",
    "bars",
    "rear",
    "front",
    "quarter",
    "side",
    "sill",
    "fender",
    "guard",
    "guards",
    "mirror",
    "window",
    "lh",
    "rh",
    "left",
    "right",
    "driver",
    "passenger",
    "both",
}


@dataclass(frozen=True)
class Rule:
    rule_id: str
    pattern: re.Pattern
    category: str
    severity: bool
    priority: int


@dataclass(frozen=True)
class DictEntry:
    entry_id: str
    pattern: re.Pattern
    category: str
    severity: bool


def normalize_text(text: str) -> str:
    if text is None:
        return ""
    value = unicodedata.normalize("NFKC", str(text))
    value = value.replace("\r\n", "\n")
    value = value.lower()
    value = re.sub(r"\s+", " ", value).strip()
    if not value:
        return ""
    for raw, expanded in ABBREV_MAP.items():
        value = re.sub(rf"\b{re.escape(raw)}\b", expanded, value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def tokenize(text: str) -> List[str]:
    if not text:
        return []
    return re.findall(r"[a-z0-9]+", text.lower())


def _contains_multiple_defect_heads(text: str) -> bool:
    tokens = set(tokenize(text))
    hits = tokens.intersection(DEFECT_KEYWORDS)
    if hits and hits.issubset({"paint", "peeling", "peel", "fade", "fading", "faded"}):
        return False
    return len(hits) >= 2


def split_defect_lines(text: str) -> List[str]:
    if not text:
        return []
    split_rules = _load_split_rules_v2()
    if split_rules:
        return _split_with_v2_rules(str(text), split_rules)
    raw = str(text)
    raw = raw.replace("&amp;", "and")
    raw = raw.replace("â€¢", "\n")
    raw = re.sub(r"\s+\|\s+|\s+-\s+", "\n", raw)
    raw = raw.replace(";", "\n")
    parts = [part.strip() for part in re.split(r"[\n\r]+", raw) if part.strip()]
    if not parts:
        return []
    output: List[str] = []
    for part in parts:
        if _contains_multiple_defect_heads(part) and re.search(r"\b(and|&)\b", part, re.IGNORECASE):
            split_parts = re.split(r"\b(?:and|&)\b", part, flags=re.IGNORECASE)
            split_parts = [p.strip(" ,") for p in split_parts if p.strip(" ,")]
            if len(split_parts) > 1:
                output.extend(split_parts)
                continue
        output.append(part)
    # Merge dangling location-only fragments back into previous defect line.
    merged: List[str] = []
    for part in output:
        tokens = tokenize(part)
        if (
            merged
            and len(tokens) <= 3
            and tokens
            and all(token in LOCATION_WORDS for token in tokens)
        ):
            merged[-1] = f"{merged[-1].rstrip(', ')} and {part}"
        else:
            merged.append(part)
    return merged


def _load_rules(path: Path | None = None) -> List[Rule]:
    source = path or RULES_PATH
    if not source.exists():
        return []
    rules: List[Rule] = []
    with source.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rule_id = str(row.get("rule_id") or "").strip()
            pattern = str(row.get("pattern") or "").strip()
            category = str(row.get("category") or "").strip().lower()
            severity = str(row.get("severity") or "").strip()
            priority = str(row.get("priority") or "").strip()
            if not rule_id or not pattern or not category:
                continue
            pattern = pattern.replace("\\\\", "\\")
            try:
                priority_val = int(priority)
            except ValueError:
                priority_val = 100
            severity_flag = str(severity).strip() in {"1", "true", "yes"}
            rules.append(
                Rule(
                    rule_id=rule_id,
                    pattern=re.compile(pattern, re.IGNORECASE),
                    category=category,
                    severity=severity_flag,
                    priority=priority_val,
                )
            )
    rules.sort(key=lambda r: r.priority)
    return rules


def map_categories(text: str, tokens: List[str], rules: Iterable[Rule] | None = None) -> Tuple[List[str], bool, List[str]]:
    v2_entries = _load_v2_dictionary()
    if v2_entries:
        matched, severity, trace = _map_categories_v2(text, v2_entries)
        if matched and matched != ["unknown"]:
            return matched, severity, trace
    rules = list(rules) if rules is not None else _load_rules()
    if not text:
        return ["unknown"], False, ["unknown"]
    matched: List[str] = []
    rule_trace: List[str] = []
    severity_flag = False
    for rule in rules:
        if rule.pattern.search(text):
            if rule.category not in matched:
                matched.append(rule.category)
            rule_trace.append(rule.rule_id)
            if rule.severity:
                severity_flag = True
    if not matched:
        return ["unknown"], False, ["unknown"]
    return matched, severity_flag, rule_trace


def load_rules() -> List[Rule]:
    return _load_rules()


def estimate_component_count(text: str) -> int:
    if not text:
        return 1
    lowered = text.lower()
    if re.search(r"\b(tail\s*lights|taillights)\b", lowered):
        return 2
    if re.search(r"\b(both seats|both seat|both)\b", lowered) and "seat" in lowered:
        return 2
    if re.search(r"\bfront and rear\b", lowered) and "bar" in lowered:
        return 2
    if re.search(r"\b(numerous|multiple|various)\b", lowered) and "panel" in lowered:
        return 3
    return 1


def _load_v2_dictionary() -> List[DictEntry]:
    if not RULES_V2_PATH.exists():
        return []
    data = yaml.safe_load(RULES_V2_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return []
    entries = data.get("entries", [])
    if not isinstance(entries, list):
        return []
    out: List[DictEntry] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        raw_phrase = str(entry.get("raw_phrase") or "").strip()
        pattern_text = str(entry.get("pattern") or "").strip()
        category = str(entry.get("category") or "").strip().lower()
        canonical_defect = str(entry.get("canonical_defect") or raw_phrase).strip()
        severity_hint = str(entry.get("severity_hint") or "").strip().lower()
        if not category:
            continue
        if pattern_text:
            pattern = pattern_text
        elif raw_phrase:
            pattern = rf"\b{re.escape(raw_phrase)}\b"
        else:
            continue
        severity = severity_hint in {"medium", "high", "critical", "severe"}
        out.append(
            DictEntry(
                entry_id=canonical_defect or raw_phrase or pattern,
                pattern=re.compile(pattern, re.IGNORECASE),
                category=category,
                severity=severity,
            )
        )
    return out


def _map_categories_v2(text: str, entries: List[DictEntry]) -> Tuple[List[str], bool, List[str]]:
    if not text:
        return ["unknown"], False, ["unknown"]
    matched: List[str] = []
    trace: List[str] = []
    severity = False
    for entry in entries:
        if entry.pattern.search(text):
            if entry.category not in matched:
                matched.append(entry.category)
            trace.append(entry.entry_id)
            if entry.severity:
                severity = True
    if not matched:
        return ["unknown"], False, ["unknown"]
    return matched, severity, trace


def _load_split_rules_v2() -> dict:
    if not SPLIT_RULES_V2_PATH.exists():
        return {}
    data = yaml.safe_load(SPLIT_RULES_V2_PATH.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _apply_synonyms(text: str, synonyms: dict) -> str:
    result = text
    for raw, norm in synonyms.items():
        result = re.sub(rf"\b{re.escape(str(raw))}\b", str(norm), result, flags=re.IGNORECASE)
    return result


def _strip_punctuation(text: str) -> str:
    return re.sub(r"[^\w\s]", " ", text)


def _split_with_v2_rules(text: str, rules: dict) -> List[str]:
    raw = text.replace("&amp;", "and").replace("Ã¢â‚¬Â¢", "\n")
    for splitter in rules.get("splitters", []):
        if not splitter:
            continue
        raw = raw.replace(splitter, "\n")
    for rule in rules.get("regex_rules", []):
        if not isinstance(rule, dict):
            continue
        pattern = str(rule.get("pattern") or "").strip()
        action = str(rule.get("action") or "").strip().lower()
        if not pattern or action != "split":
            continue
        try:
            raw = re.sub(pattern, r"\\1\n\\2", raw, flags=re.IGNORECASE)
        except re.error:
            continue
    parts = [part.strip() for part in re.split(r"[\n\r]+", raw) if part.strip()]
    if not parts:
        return []
    # Special handling: keep "marks and scratches" together, split "dents" out.
    expanded: List[str] = []
    for part in parts:
        if re.search(r"\bdents\b", part, re.IGNORECASE) and re.search(
            r"\bmarks\b", part, re.IGNORECASE
        ):
            # Example: "medium dents, marks, scratches on body ..."
            dents_match = re.search(r"\b(\w+\s+)?dents?\b", part, re.IGNORECASE)
            if dents_match:
                expanded.append(dents_match.group(0).strip())
                remainder = part[dents_match.end():].strip(" ,")
                if remainder:
                    expanded.append(remainder)
                continue
        expanded.append(part)
    parts = expanded
    cleanup = rules.get("cleanup", {}) if isinstance(rules.get("cleanup", {}), dict) else {}
    remove_words = set(
        str(word).lower() for word in rules.get("remove_words", []) if str(word).strip()
    )
    synonyms = rules.get("synonyms", {}) if isinstance(rules.get("synonyms", {}), dict) else {}
    output: List[str] = []
    for part in parts:
        text_part = part
        if cleanup.get("lowercase", True):
            text_part = text_part.lower()
        text_part = _apply_synonyms(text_part, synonyms)
        if cleanup.get("strip_punctuation", False):
            text_part = _strip_punctuation(text_part)
        if remove_words:
            tokens = [t for t in tokenize(text_part) if t not in remove_words]
            text_part = " ".join(tokens)
        if cleanup.get("trim_whitespace", True):
            text_part = re.sub(r"\s+", " ", text_part).strip()
        if text_part:
            output.append(text_part)
    merged: List[str] = []
    for part in output:
        tokens = tokenize(part)
        if merged and tokens and len(tokens) <= 3 and all(token in LOCATION_WORDS for token in tokens):
            merged[-1] = f"{merged[-1].rstrip(', ')} and {part}"
        elif merged and part in {"mark", "marks", "scratch", "scratches"}:
            merged[-1] = f"{merged[-1].rstrip(', ')} and {part}"
        else:
            merged.append(part)
    return merged
