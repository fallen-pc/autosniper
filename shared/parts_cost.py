"""Estimate repair parts cost using the Harvey Wreckers price list."""

from __future__ import annotations

from functools import lru_cache
import json
import re
from pathlib import Path
from typing import Iterable

import pandas as pd

PRICE_LOOKUP_PATH = Path("assets/harvey_parts_price_lookup.csv")

PRICE_NUMBER_RE = re.compile(r"\d+(?:,\d+)*(?:\.\d+)?")

TAG_KEYWORDS: dict[str, tuple[str, ...]] = {
    "engine_mechanical": ("engine", "gearbox", "transmission", "clutch", "diff"),
    "electrical": ("sensor", "ecu", "computer", "alternator", "abs", "air bag", "wiring"),
    "non_operational": ("starter", "fuel pump", "ignition"),
    "suspension_brakes": ("brake", "suspension", "control arm", "strut", "shock", "steering"),
    "interior": ("seat", "trim", "carpet", "console", "dashboard", "interior"),
    "body_exterior": ("bumper", "head light", "taillight", "bonnet", "door", "guard", "panel"),
    "tyres_wheels": ("wheel", "rim", "tyre"),
    "general_wear": ("handle", "mould", "garnish"),
    "unknown_untested": (),
}

DEFAULT_BASE_COSTS: dict[str, float] = {
    "engine_mechanical": 1500.0,
    "electrical": 600.0,
    "non_operational": 800.0,
    "suspension_brakes": 450.0,
    "interior": 250.0,
    "body_exterior": 300.0,
    "tyres_wheels": 220.0,
    "general_wear": 120.0,
    "unknown_untested": 300.0,
}

TIER_MULTIPLIERS = {
    "low": 0.6,
    "mid": 1.0,
    "high": 1.5,
}


def _parse_price_value(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"p.o.a", "poa", "n/a"}:
        return None
    matches = PRICE_NUMBER_RE.findall(text.replace("/", " ").replace("\\", " "))
    numbers: list[float] = []
    for match in matches:
        sanitized = match.replace(",", "")
        try:
            numbers.append(float(sanitized))
        except ValueError:
            continue
    if not numbers:
        return None
    return sum(numbers) / len(numbers)


@lru_cache(maxsize=1)
def _load_price_table(path: Path = PRICE_LOOKUP_PATH) -> pd.DataFrame:
    table = pd.read_csv(path)
    table["part"] = table["part"].astype(str).str.strip()
    # Drop rows that are just the section headers ("A", "B", etc.).
    table = table[table["part"].str.len() > 1].copy()
    table["part_lower"] = table["part"].str.lower()
    for column in ("pick_price", "warranty_price", "core_deposit", "models_2008_on"):
        value_column = f"{column}_value"
        table[value_column] = table[column].apply(_parse_price_value)
    table["base_price"] = table[
        ["pick_price_value", "warranty_price_value", "core_deposit_value", "models_2008_on_value"]
    ].median(axis=1, skipna=True)
    return table


@lru_cache(maxsize=1)
def _tag_base_costs() -> dict[str, float]:
    table = _load_price_table()
    costs: dict[str, float] = {}
    for tag, keywords in TAG_KEYWORDS.items():
        if not keywords:
            costs[tag] = DEFAULT_BASE_COSTS.get(tag, 0.0)
            continue
        mask = False
        for keyword in keywords:
            keyword = keyword.strip()
            if not keyword:
                continue
            current_mask = table["part_lower"].str.contains(keyword.lower(), na=False)
            mask = current_mask if mask is False else (mask | current_mask)
        if mask is False:
            mask = pd.Series(False, index=table.index)
        values = table.loc[mask, "base_price"].dropna()
        if not values.empty:
            costs[tag] = float(values.median())
        else:
            costs[tag] = DEFAULT_BASE_COSTS.get(tag, 0.0)
    return costs


def _severity_tier(severity: int) -> str:
    if severity <= 10:
        return "low"
    if severity <= 30:
        return "mid"
    return "high"


def estimate_parts_cost(tags: Iterable[str], severity: int) -> tuple[float, str]:
    """Estimate a parts-only repair cost for the supplied tags."""
    tier = _severity_tier(severity)
    multiplier = TIER_MULTIPLIERS.get(tier, 1.0)
    base_costs = _tag_base_costs()
    details = []
    total = 0.0
    for tag in tags:
        tag = tag.strip()
        if not tag:
            continue
        base = base_costs.get(tag, DEFAULT_BASE_COSTS.get(tag, 0.0))
        contribution = base * multiplier
        total += contribution
        details.append({"tag": tag, "base_cost": round(base, 2), "tier": tier, "multiplier": multiplier})
    serialized = json.dumps(details, ensure_ascii=False)
    return round(total, 2), serialized
