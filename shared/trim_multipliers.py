"""Trim multiplier lookup for curve pricing."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Tuple


TRIM_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "trim_multipliers.yaml"


@lru_cache(maxsize=1)
def load_trim_multipliers(path: Path | None = None) -> Dict[str, Any]:
    config_path = path or TRIM_CONFIG_PATH
    if not config_path.exists():
        return {}
    try:
        import yaml
    except ImportError:  # pragma: no cover
        return {"_error": "pyyaml_missing", "_path": str(config_path)}
    with config_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _normalize_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def apply_trim_multiplier(
    base_price: float | None,
    group_id: str | None,
    trim_text: object,
    odometer: float | int | None,
    config: Dict[str, Any],
) -> Tuple[float | None, float | None]:
    if base_price is None:
        return base_price, None
    if not group_id:
        return base_price, None
    if not config:
        return base_price, None

    group_cfg = config.get("groups", {}).get(group_id)
    if not isinstance(group_cfg, dict):
        return base_price, None

    trim_norm = _normalize_text(trim_text)
    if not trim_norm:
        return base_price, None

    matched_rule = None
    for key, rule in group_cfg.items():
        if key.startswith("_"):
            continue
        if not isinstance(rule, dict):
            continue
        key_norm = _normalize_text(key)
        if not key_norm:
            continue
        if trim_norm == key_norm or key_norm in trim_norm:
            matched_rule = rule
            break

    if not matched_rule:
        return base_price, None

    if matched_rule.get("method") != "multiplier_by_km":
        return base_price, None

    if odometer is None:
        return base_price, None

    try:
        odo_val = float(odometer)
    except (TypeError, ValueError):
        return base_price, None

    for band in matched_rule.get("by_km", []):
        max_km = band.get("max_km")
        multiplier = band.get("multiplier")
        if max_km is None or multiplier is None:
            continue
        try:
            max_km_val = float(max_km)
            multiplier_val = float(multiplier)
        except (TypeError, ValueError):
            continue
        if odo_val <= max_km_val:
            return base_price * multiplier_val, multiplier_val

    return base_price, None
