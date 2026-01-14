"""Grouping logic for restricted VIC Top-12 model universe."""

from __future__ import annotations

import re
from typing import Iterable, Tuple

STATE_ABBREVIATIONS = ("ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA")

MAKE_ALIASES = {
    "vw": "volkswagen",
    "volkswagen": "volkswagen",
    "bmw": "bmw",
    "holden": "holden",
    "toyota": "toyota",
    "ford": "ford",
    "hyundai": "hyundai",
    "mazda": "mazda",
    "nissan": "nissan",
}

MODEL_ALIASES = {
    "hilux": "hilux",
    "golf": "golf",
    "commodore": "commodore",
    "cruze": "cruze",
    "territory": "territory",
    "i30": "i30",
    "corolla": "corolla",
    "3series": "3series",
    "3seriesbmw": "3series",
    "3series3": "3series",
    "captiva": "captiva",
    "ranger": "ranger",
    "cx5": "cx5",
    "navara": "navara",
}

TOP_12_MODELS = {
    ("toyota", "hilux"),
    ("volkswagen", "golf"),
    ("holden", "commodore"),
    ("holden", "cruze"),
    ("ford", "territory"),
    ("hyundai", "i30"),
    ("toyota", "corolla"),
    ("bmw", "3series"),
    ("holden", "captiva"),
    ("ford", "ranger"),
    ("mazda", "cx5"),
    ("nissan", "navara"),
}

GROUP_IDS = [
    "toyota_hilux_dualcab_ute_diesel_auto_sr5_4x4",
    "volkswagen_golf_hatch_petrol_auto_base",
    "holden_commodore_sedan_petrol_auto_v6",
    "holden_commodore_wagon_petrol_auto_v6",
    "holden_cruze_hatch_petrol_auto_4cyl",
    "ford_territory_suv_diesel_auto_4cyl",
    "hyundai_i30_hatch_petrol_auto_na_active_elite",
    "toyota_corolla_hatch_petrol_auto",
    "toyota_corolla_sedan_petrol_auto",
    "bmw_3series_sedan_petrol_auto_4cyl_20",
    "holden_captiva_suv_diesel_auto_4cyl",
    "ford_ranger_dualcab_ute_diesel_auto",
    "mazda_cx5_suv_petrol_auto_20",
    "mazda_cx5_suv_petrol_auto_25",
    "nissan_navara_dualcab_ute_diesel_auto",
]

REPAIRABLE_TOKENS = (
    "wovr",
    "write off",
    "write-off",
    "repairable",
    "statutory",
)
CONDITION_BAD_TOKENS = (
    "hail",
    "flood",
    "fire",
    "wreck",
    "parts",
    "spares",
    "engine issue",
    "needs motor",
    "blown",
    "not running",
)


def _normalize_key(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    return re.sub(r"[^a-z0-9]+", "", text)


def _normalize_make(value: object) -> str:
    key = _normalize_key(value)
    return MAKE_ALIASES.get(key, key)


def _normalize_model(value: object) -> str:
    key = _normalize_key(value)
    return MODEL_ALIASES.get(key, key)


def extract_state(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    upper = text.upper()
    for state in STATE_ABBREVIATIONS:
        if state in upper:
            return state
    if "," in text:
        return text.split(",")[-1].strip().upper()
    parts = text.split()
    if parts:
        return parts[-1].strip().upper()
    return upper


def _extract_state_from_row(row: object) -> str:
    for field in ("location_state", "rego_state", "location"):
        state = extract_state(getattr(row, "get", lambda _: None)(field))
        if state:
            return state
    return ""


def _text_blob(row: object) -> str:
    parts = []
    getter = getattr(row, "get", lambda _: None)
    for field in ("variant", "body_type", "general_condition", "model", "make", "url"):
        value = getter(field)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            parts.append(text)
    return " ".join(parts).lower()


def _parse_engine_capacity_liters(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).lower().strip()
    if not text:
        return None
    numbers = re.findall(r"\d+(?:\.\d+)?", text)
    if not numbers:
        return None
    try:
        num = float(numbers[0])
    except ValueError:
        return None
    if "cc" in text or num > 20:
        return num / 1000.0
    return num


def _extract_engine_hint(text: str) -> float | None:
    if not text:
        return None
    match = re.search(r"\b(\d\.\d)\s*l\b", text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    match = re.search(r"\b(\d\.\d)\b", text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    match = re.search(r"\b(\d{3,4})\s*cc\b", text)
    if match:
        try:
            return float(match.group(1)) / 1000.0
        except ValueError:
            return None
    return None


def _parse_cylinders(value: object) -> int | None:
    if value is None:
        return None
    text = str(value).lower()
    match = re.search(r"\b(\d+)\b", text)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    if "v6" in text:
        return 6
    if "v8" in text:
        return 8
    return None


def _has_any(text: str, keywords: Iterable[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _match_regex(text: str, pattern: str) -> bool:
    return bool(re.search(pattern, text, flags=re.IGNORECASE))


def _is_auto(row: object, text: str) -> bool:
    transmission = str(getattr(row, "get", lambda _: None)("transmission") or "").lower()
    if "manual" in transmission:
        return False
    if any(token in transmission for token in ("auto", "automatic", "cvt", "dsg")):
        return True
    return _match_regex(text, r"\bauto\b|\bautomatic\b|\bcvt\b|\bdsg\b")


def _is_manual(row: object, text: str) -> bool:
    transmission = str(getattr(row, "get", lambda _: None)("transmission") or "").lower()
    if "manual" in transmission:
        return True
    return _match_regex(text, r"\bmanual\b|\bman\b")


def _fuel_type(row: object, text: str) -> str:
    raw = str(getattr(row, "get", lambda _: None)("fuel_type") or "").lower()
    if "diesel" in raw:
        return "diesel"
    if "hybrid" in raw:
        return "hybrid"
    if "petrol" in raw or "gasoline" in raw or "unleaded" in raw:
        return "petrol"
    if "diesel" in text:
        return "diesel"
    if "hybrid" in text:
        return "hybrid"
    if "petrol" in text:
        return "petrol"
    return ""


def _body_text(row: object) -> str:
    value = getattr(row, "get", lambda _: None)("body_type")
    return str(value or "").lower()


def _has_body(body_text: str, text: str, patterns: Iterable[str]) -> bool:
    if any(token in body_text for token in patterns):
        return True
    return any(token in text for token in patterns)


def _has_token(text: str, pattern: str) -> bool:
    return _match_regex(text, pattern)


def _is_dual_cab(text: str, body_text: str) -> bool:
    return _has_body(body_text, text, ("dual cab", "dualcab", "double cab"))


def _is_cab_chassis(text: str, body_text: str) -> bool:
    return _has_body(body_text, text, ("cab chassis", "cab-chassis", "cabchassis"))


def _is_single_cab(text: str, body_text: str) -> bool:
    return _has_body(body_text, text, ("single cab", "singlecab"))


def _is_extra_cab(text: str, body_text: str) -> bool:
    return _has_body(body_text, text, ("extra cab", "extracab", "super cab", "king cab"))


def _is_ute(text: str, body_text: str) -> bool:
    return _has_body(body_text, text, ("ute", "utility", "pickup", "pick-up"))


def _is_hatch(text: str, body_text: str) -> bool:
    return _has_body(body_text, text, ("hatch", "hatchback"))


def _is_sedan(text: str, body_text: str) -> bool:
    return _has_body(body_text, text, ("sedan",))


def _is_wagon(text: str, body_text: str) -> bool:
    return _has_body(body_text, text, ("wagon",))


def _is_suv(text: str, body_text: str) -> bool:
    return _has_body(body_text, text, ("suv", "wagon", "sport utility"))


def _is_4x4(text: str) -> bool:
    return _match_regex(text, r"\b4x4\b|\b4wd\b|\bawd\b")


def _is_4x2(text: str) -> bool:
    return _match_regex(text, r"\b4x2\b|\b2wd\b")


def _has_hi_rider(text: str) -> bool:
    return _match_regex(text, r"\bhi[- ]?rider\b")


def _passes_global_exclusions(text: str) -> Tuple[bool, str]:
    if _has_any(text, REPAIRABLE_TOKENS):
        return False, "REPAIRABLE"
    if _has_any(text, CONDITION_BAD_TOKENS):
        return False, "CONDITION_BAD"
    return True, ""


def _assign_hilux(row: object, text: str, body_text: str) -> Tuple[str | None, str]:
    if _fuel_type(row, text) != "diesel":
        return None, "BAD_GROUP:FUEL_MISMATCH"
    if not _is_auto(row, text):
        return None, "BAD_GROUP:TRANS_MISMATCH"
    if _is_cab_chassis(text, body_text):
        return None, "BAD_GROUP:BODY_MISMATCH"
    if _is_single_cab(text, body_text) or _is_extra_cab(text, body_text):
        return None, "BAD_GROUP:CAB_MISMATCH"
    if not _is_dual_cab(text, body_text):
        return None, "BAD_GROUP:CAB_MISMATCH"
    if not _is_ute(text, body_text):
        return None, "BAD_GROUP:BODY_MISMATCH"
    if _is_4x2(text) or _has_hi_rider(text):
        return None, "BAD_GROUP:DRIVETRAIN_MISMATCH"
    if not _is_4x4(text):
        return None, "BAD_GROUP:DRIVETRAIN_MISMATCH"
    if not _has_token(text, r"\bsr5\b"):
        return None, "BAD_GROUP:TRIM_MISMATCH"
    engine_liters = _parse_engine_capacity_liters(getattr(row, "get", lambda _: None)("engine_capacity"))
    if engine_liters is None:
        engine_liters = _extract_engine_hint(text)
    if engine_liters is not None and not (2.7 <= engine_liters <= 3.1):
        return None, "BAD_GROUP:ENGINE_MISMATCH"
    return "toyota_hilux_dualcab_ute_diesel_auto_sr5_4x4", ""


def _assign_golf(row: object, text: str, body_text: str) -> Tuple[str | None, str]:
    if _is_wagon(text, body_text):
        return None, "BAD_GROUP:BODY_MISMATCH"
    if not _is_hatch(text, body_text):
        return None, "BAD_GROUP:BODY_MISMATCH"
    if _fuel_type(row, text) != "petrol":
        return None, "BAD_GROUP:FUEL_MISMATCH"
    if not _is_auto(row, text):
        return None, "BAD_GROUP:TRANS_MISMATCH"
    if _match_regex(text, r"\bgti\b|\br-?line\b|\bclubsport\b|\bedition\s*40\b|\bgolf\s*r\b"):
        return None, "BAD_GROUP:PERFORMANCE_TRIM"
    engine_liters = _parse_engine_capacity_liters(getattr(row, "get", lambda _: None)("engine_capacity"))
    if engine_liters is not None and not (1.3 <= engine_liters <= 1.9):
        return None, "BAD_GROUP:ENGINE_MISMATCH"
    return "volkswagen_golf_hatch_petrol_auto_base", ""


def _assign_commodore(row: object, text: str, body_text: str) -> Tuple[str | None, str]:
    if _is_manual(row, text):
        return None, "BAD_GROUP:TRANS_MISMATCH"
    if _fuel_type(row, text) != "petrol":
        return None, "BAD_GROUP:FUEL_MISMATCH"
    if _match_regex(text, r"\bss\b|\bsv8\b|\bv8\b|\bclubsport\b|\bmaloo\b|\bgts\b|\bhsv\b"):
        return None, "BAD_GROUP:PERFORMANCE_TRIM"
    cylinders = _parse_cylinders(getattr(row, "get", lambda _: None)("no_of_cylinders"))
    if cylinders is None:
        cylinders = 6 if _match_regex(text, r"\bv6\b|\bsv6\b") else None
    if cylinders is not None and cylinders != 6:
        return None, "BAD_GROUP:ENGINE_MISMATCH"
    if _is_sedan(text, body_text):
        return "holden_commodore_sedan_petrol_auto_v6", ""
    if _is_wagon(text, body_text):
        return "holden_commodore_wagon_petrol_auto_v6", ""
    return None, "BAD_GROUP:BODY_MISMATCH"


def _assign_cruze(row: object, text: str, body_text: str) -> Tuple[str | None, str]:
    if not _is_hatch(text, body_text):
        return None, "BAD_GROUP:BODY_MISMATCH"
    if _fuel_type(row, text) != "petrol":
        return None, "BAD_GROUP:FUEL_MISMATCH"
    if not _is_auto(row, text):
        return None, "BAD_GROUP:TRANS_MISMATCH"
    cylinders = _parse_cylinders(getattr(row, "get", lambda _: None)("no_of_cylinders"))
    if cylinders is not None and cylinders != 4:
        return None, "BAD_GROUP:ENGINE_MISMATCH"
    return "holden_cruze_hatch_petrol_auto_4cyl", ""


def _assign_territory(row: object, text: str, body_text: str) -> Tuple[str | None, str]:
    if not _is_suv(text, body_text):
        return None, "BAD_GROUP:BODY_MISMATCH"
    if _fuel_type(row, text) != "diesel":
        return None, "BAD_GROUP:FUEL_MISMATCH"
    if not _is_auto(row, text):
        return None, "BAD_GROUP:TRANS_MISMATCH"
    cylinders = _parse_cylinders(getattr(row, "get", lambda _: None)("no_of_cylinders"))
    if cylinders is not None and cylinders != 4:
        return None, "BAD_GROUP:ENGINE_MISMATCH"
    return "ford_territory_suv_diesel_auto_4cyl", ""


def _assign_i30(row: object, text: str, body_text: str) -> Tuple[str | None, str]:
    if not _is_hatch(text, body_text):
        return None, "BAD_GROUP:BODY_MISMATCH"
    if _fuel_type(row, text) != "petrol":
        return None, "BAD_GROUP:FUEL_MISMATCH"
    if not _is_auto(row, text):
        return None, "BAD_GROUP:TRANS_MISMATCH"
    if _match_regex(text, r"\bi30n\b|\bn[- ]?line\b|\bt-?gdi\b|\bturbo\b|\bn performance\b"):
        return None, "BAD_GROUP:PERFORMANCE_TRIM"
    return "hyundai_i30_hatch_petrol_auto_na_active_elite", ""


def _assign_corolla(row: object, text: str, body_text: str) -> Tuple[str | None, str]:
    if _fuel_type(row, text) != "petrol":
        return None, "BAD_GROUP:FUEL_MISMATCH"
    if _match_regex(text, r"\bhybrid\b"):
        return None, "BAD_GROUP:FUEL_MISMATCH"
    if not _is_auto(row, text):
        return None, "BAD_GROUP:TRANS_MISMATCH"
    if _is_hatch(text, body_text):
        return "toyota_corolla_hatch_petrol_auto", ""
    if _is_sedan(text, body_text):
        return "toyota_corolla_sedan_petrol_auto", ""
    return None, "BAD_GROUP:BODY_MISMATCH"


def _assign_bmw_3series(row: object, text: str, body_text: str) -> Tuple[str | None, str]:
    if not _is_sedan(text, body_text):
        return None, "BAD_GROUP:BODY_MISMATCH"
    if _fuel_type(row, text) != "petrol":
        return None, "BAD_GROUP:FUEL_MISMATCH"
    if not _is_auto(row, text):
        return None, "BAD_GROUP:TRANS_MISMATCH"
    if _match_regex(text, r"\b330\b|\b335\b|\b340\b|\bm3\b"):
        return None, "BAD_GROUP:PERFORMANCE_TRIM"
    cylinders = _parse_cylinders(getattr(row, "get", lambda _: None)("no_of_cylinders"))
    if cylinders is None and _match_regex(text, r"\b(318i|320i|328i)\b"):
        cylinders = 4
    if cylinders is not None and cylinders != 4:
        return None, "BAD_GROUP:ENGINE_MISMATCH"
    engine_liters = _parse_engine_capacity_liters(getattr(row, "get", lambda _: None)("engine_capacity"))
    if engine_liters is None:
        engine_liters = _extract_engine_hint(text)
    if engine_liters is not None and not (1.8 <= engine_liters <= 2.1):
        return None, "BAD_GROUP:ENGINE_MISMATCH"
    return "bmw_3series_sedan_petrol_auto_4cyl_20", ""


def _assign_captiva(row: object, text: str, body_text: str) -> Tuple[str | None, str]:
    if not _is_suv(text, body_text):
        return None, "BAD_GROUP:BODY_MISMATCH"
    if _fuel_type(row, text) != "diesel":
        return None, "BAD_GROUP:FUEL_MISMATCH"
    if not _is_auto(row, text):
        return None, "BAD_GROUP:TRANS_MISMATCH"
    cylinders = _parse_cylinders(getattr(row, "get", lambda _: None)("no_of_cylinders"))
    if cylinders is not None and cylinders != 4:
        return None, "BAD_GROUP:ENGINE_MISMATCH"
    if _match_regex(text, r"\bv6\b"):
        return None, "BAD_GROUP:ENGINE_MISMATCH"
    return "holden_captiva_suv_diesel_auto_4cyl", ""


def _assign_ranger(row: object, text: str, body_text: str) -> Tuple[str | None, str]:
    if _is_cab_chassis(text, body_text):
        return None, "BAD_GROUP:BODY_MISMATCH"
    if _is_single_cab(text, body_text) or _is_extra_cab(text, body_text):
        return None, "BAD_GROUP:BODY_MISMATCH"
    if not _is_dual_cab(text, body_text):
        return None, "BAD_GROUP:CAB_MISMATCH"
    if _fuel_type(row, text) != "diesel":
        return None, "BAD_GROUP:FUEL_MISMATCH"
    if not _is_auto(row, text):
        return None, "BAD_GROUP:TRANS_MISMATCH"
    return "ford_ranger_dualcab_ute_diesel_auto", ""


def _assign_cx5(row: object, text: str, body_text: str) -> Tuple[str | None, str]:
    if not _is_suv(text, body_text):
        return None, "BAD_GROUP:BODY_MISMATCH"
    if _fuel_type(row, text) != "petrol":
        return None, "BAD_GROUP:FUEL_MISMATCH"
    if not _is_auto(row, text):
        return None, "BAD_GROUP:TRANS_MISMATCH"
    if _match_regex(text, r"\bdiesel\b|\bturbo\b"):
        return None, "BAD_GROUP:ENGINE_MISMATCH"
    engine_liters = _parse_engine_capacity_liters(getattr(row, "get", lambda _: None)("engine_capacity"))
    if engine_liters is None:
        engine_liters = _extract_engine_hint(text)
    if engine_liters is None:
        return None, "INSUFFICIENT_DATA"
    if 1.9 <= engine_liters <= 2.1:
        return "mazda_cx5_suv_petrol_auto_20", ""
    if 2.3 <= engine_liters <= 2.6:
        return "mazda_cx5_suv_petrol_auto_25", ""
    return None, "BAD_GROUP:ENGINE_MISMATCH"


def _assign_navara(row: object, text: str, body_text: str) -> Tuple[str | None, str]:
    if _is_cab_chassis(text, body_text):
        return None, "BAD_GROUP:BODY_MISMATCH"
    if _is_single_cab(text, body_text) or _is_extra_cab(text, body_text):
        return None, "BAD_GROUP:BODY_MISMATCH"
    if not _is_dual_cab(text, body_text):
        return None, "BAD_GROUP:CAB_MISMATCH"
    if _fuel_type(row, text) != "diesel":
        return None, "BAD_GROUP:FUEL_MISMATCH"
    if not _is_auto(row, text):
        return None, "BAD_GROUP:TRANS_MISMATCH"
    return "nissan_navara_dualcab_ute_diesel_auto", ""


def assign_group_id(row: object) -> Tuple[str | None, str]:
    """
    Return (group_id, reason_code). group_id is None if listing is excluded.
    """
    state = _extract_state_from_row(row)
    if not state:
        return None, "INSUFFICIENT_DATA"
    if state != "VIC":
        return None, "NON_VIC"

    make = _normalize_make(getattr(row, "get", lambda _: None)("make"))
    model = _normalize_model(getattr(row, "get", lambda _: None)("model"))
    if (make, model) not in TOP_12_MODELS:
        return None, "NOT_TOP12"

    text = _text_blob(row)
    allowed, reason = _passes_global_exclusions(text)
    if not allowed:
        return None, reason

    body_text = _body_text(row)

    if (make, model) == ("toyota", "hilux"):
        return _assign_hilux(row, text, body_text)
    if (make, model) == ("volkswagen", "golf"):
        return _assign_golf(row, text, body_text)
    if (make, model) == ("holden", "commodore"):
        return _assign_commodore(row, text, body_text)
    if (make, model) == ("holden", "cruze"):
        return _assign_cruze(row, text, body_text)
    if (make, model) == ("ford", "territory"):
        return _assign_territory(row, text, body_text)
    if (make, model) == ("hyundai", "i30"):
        return _assign_i30(row, text, body_text)
    if (make, model) == ("toyota", "corolla"):
        return _assign_corolla(row, text, body_text)
    if (make, model) == ("bmw", "3series"):
        return _assign_bmw_3series(row, text, body_text)
    if (make, model) == ("holden", "captiva"):
        return _assign_captiva(row, text, body_text)
    if (make, model) == ("ford", "ranger"):
        return _assign_ranger(row, text, body_text)
    if (make, model) == ("mazda", "cx5"):
        return _assign_cx5(row, text, body_text)
    if (make, model) == ("nissan", "navara"):
        return _assign_navara(row, text, body_text)

    return None, "BAD_GROUP"
