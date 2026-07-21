from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import yaml

from shared.repair_review import LIVE_QUEUE_PATH, safe_text


REPORT_DIR = Path("CSV_data/reports")
AI_SUGGESTIONS_PATH = REPORT_DIR / "repair_review_ai_suggestions.csv"
DICTIONARY_PATH = Path("config/condition_dictionary_v2.yaml")

AI_SUGGESTION_COLUMNS = [
    "repair_key",
    "repair_item",
    "ai_decision",
    "ai_target_category",
    "ai_canonical_defect",
    "ai_severity_hint",
    "ai_cost_model",
    "ai_confidence",
    "ai_rationale",
    "model",
    "suggested_at",
]

DECISION_OPTIONS = [
    "Add dictionary rule",
    "Ignore as boilerplate",
    "Mark feature-list leak",
    "Mark context fragment",
    "Mark usage risk",
    "Leave unclassified",
]

CATEGORY_OPTIONS = [
    "",
    "cosmetic",
    "glass",
    "replacement",
    "interior",
    "mechanical",
    "structural",
    "boilerplate",
    "usage_risk",
    "context_fragment",
    "feature_leak",
]

SEVERITY_OPTIONS = ["", "low", "medium", "high"]
COST_MODEL_OPTIONS = ["", "no_cost", "cosmetic_panel", "fixed_replacement", "glass", "hard_avoid"]


@dataclass(frozen=True)
class ClassifierResult:
    considered: int
    suggested: int
    output_path: Path
    skipped_reason: str = ""


def load_ai_suggestions(path: Path = AI_SUGGESTIONS_PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=AI_SUGGESTION_COLUMNS)
    try:
        df = pd.read_csv(path).fillna("")
    except Exception:
        return pd.DataFrame(columns=AI_SUGGESTION_COLUMNS)
    for column in AI_SUGGESTION_COLUMNS:
        if column not in df.columns:
            df[column] = ""
    return df[AI_SUGGESTION_COLUMNS]


def _load_queue(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path).fillna("")
    for column in ["repair_key", "repair_item", "status", "category", "canonical_defects"]:
        if column not in df.columns:
            df[column] = ""
    return df


def _needs_ai_suggestion(row: pd.Series) -> bool:
    status = safe_text(row.get("status"))
    category = safe_text(row.get("category"))
    canonical = safe_text(row.get("canonical_defects"))
    return status in {"unclassified", "not_assessed_after_hard_avoid"} or category in {
        "unclassified",
        "not_assessed",
    } or not canonical


def _dictionary_vocab(path: Path = DICTIONARY_PATH) -> dict[str, list[str]]:
    if not path.exists():
        return {"categories": CATEGORY_OPTIONS, "canonical_defects": []}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {"categories": CATEGORY_OPTIONS, "canonical_defects": []}
    entries = payload.get("entries") or []
    defects = sorted(
        {
            safe_text(entry.get("canonical_defect"))
            for entry in entries
            if isinstance(entry, dict) and safe_text(entry.get("canonical_defect"))
        }
    )
    categories = [safe_text(value) for value in payload.get("categories") or [] if safe_text(value)]
    return {"categories": categories or CATEGORY_OPTIONS, "canonical_defects": defects}


def _pending_rows(queue_df: pd.DataFrame, suggestions_df: pd.DataFrame, *, force: bool) -> pd.DataFrame:
    if queue_df.empty:
        return queue_df
    working = queue_df[queue_df.apply(_needs_ai_suggestion, axis=1)].copy()
    working["repair_key"] = working["repair_key"].map(safe_text)
    working = working[working["repair_key"] != ""]
    working = working.drop_duplicates(subset=["repair_key"], keep="last")
    if force or suggestions_df.empty:
        return working
    suggested_keys = set(suggestions_df["repair_key"].map(safe_text))
    return working[~working["repair_key"].isin(suggested_keys)].copy()


def _build_prompt(rows: pd.DataFrame) -> str:
    vocab = _dictionary_vocab()
    examples: list[dict[str, str]] = []
    for _, row in rows.iterrows():
        examples.append(
            {
                "repair_key": safe_text(row.get("repair_key")),
                "repair_item": safe_text(row.get("repair_item")),
                "status": safe_text(row.get("status")),
                "category": safe_text(row.get("category")),
                "example_vehicles": safe_text(row.get("example_vehicles")),
                "example_condition_notes": safe_text(row.get("example_condition_notes"))[:1200],
            }
        )
    return json.dumps(
        {
            "task": (
                "Classify auction vehicle condition fragments for a repair review queue. "
                "Return conservative suggestions only. Use Leave unclassified when the text is vague."
            ),
            "decision_options": DECISION_OPTIONS,
            "category_options": CATEGORY_OPTIONS,
            "severity_options": SEVERITY_OPTIONS,
            "cost_model_options": COST_MODEL_OPTIONS,
            "known_dictionary_categories": vocab["categories"],
            "known_canonical_defects": vocab["canonical_defects"][:160],
            "rules": [
                "Mechanical, structural, chassis, transmission, engine, overheating, warning-light faults should be high severity and hard_avoid.",
                "Boilerplate, feature lists, locations, legal disclaimers, roadworthy/as-is wording should not add repair cost.",
                "Use snake_case canonical defects. Prefer an existing canonical_defect when one fits.",
                "Do not classify a bare body location as damage unless damage words are present.",
            ],
            "rows": examples,
        },
        ensure_ascii=True,
    )


def _json_schema() -> dict[str, Any]:
    return {
        "name": "repair_review_ai_suggestions",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "suggestions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "repair_key": {"type": "string"},
                            "decision": {"type": "string", "enum": DECISION_OPTIONS},
                            "target_category": {"type": "string", "enum": CATEGORY_OPTIONS},
                            "canonical_defect": {"type": "string"},
                            "severity_hint": {"type": "string", "enum": SEVERITY_OPTIONS},
                            "cost_model": {"type": "string", "enum": COST_MODEL_OPTIONS},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "rationale": {"type": "string"},
                        },
                        "required": [
                            "repair_key",
                            "decision",
                            "target_category",
                            "canonical_defect",
                            "severity_hint",
                            "cost_model",
                            "confidence",
                            "rationale",
                        ],
                    },
                }
            },
            "required": ["suggestions"],
        },
        "strict": True,
    }


def _coerce_suggestions(raw: Iterable[dict[str, Any]], source_rows: pd.DataFrame, *, model: str) -> pd.DataFrame:
    source_lookup = {
        safe_text(row.get("repair_key")): safe_text(row.get("repair_item"))
        for _, row in source_rows.iterrows()
    }
    now = datetime.now(tz=timezone.utc).isoformat()
    rows: list[dict[str, object]] = []
    for item in raw:
        repair_key = safe_text(item.get("repair_key"))
        if not repair_key or repair_key not in source_lookup:
            continue
        decision = safe_text(item.get("decision"))
        target_category = safe_text(item.get("target_category"))
        severity = safe_text(item.get("severity_hint"))
        cost_model = safe_text(item.get("cost_model"))
        if decision not in DECISION_OPTIONS:
            decision = "Leave unclassified"
        if target_category not in CATEGORY_OPTIONS:
            target_category = ""
        if severity not in SEVERITY_OPTIONS:
            severity = ""
        if cost_model not in COST_MODEL_OPTIONS:
            cost_model = ""
        try:
            confidence = max(0.0, min(1.0, float(item.get("confidence"))))
        except (TypeError, ValueError):
            confidence = 0.0
        rows.append(
            {
                "repair_key": repair_key,
                "repair_item": source_lookup[repair_key],
                "ai_decision": decision,
                "ai_target_category": target_category,
                "ai_canonical_defect": safe_text(item.get("canonical_defect")),
                "ai_severity_hint": severity,
                "ai_cost_model": cost_model,
                "ai_confidence": confidence,
                "ai_rationale": safe_text(item.get("rationale")),
                "model": model,
                "suggested_at": now,
            }
        )
    return pd.DataFrame(rows, columns=AI_SUGGESTION_COLUMNS)


def _call_openai(rows: pd.DataFrame, *, model: str) -> pd.DataFrame:
    from openai import OpenAI

    client = OpenAI()
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_schema", "json_schema": _json_schema()},
        messages=[
            {
                "role": "system",
                "content": "You are a conservative vehicle repair classification assistant. Output JSON only.",
            },
            {"role": "user", "content": _build_prompt(rows)},
        ],
    )
    content = response.choices[0].message.content or "{}"
    payload = json.loads(content)
    return _coerce_suggestions(payload.get("suggestions") or [], rows, model=model)


def classify_repair_review_queue(
    *,
    queue_path: Path = LIVE_QUEUE_PATH,
    output_path: Path = AI_SUGGESTIONS_PATH,
    model: str | None = None,
    limit: int = 25,
    force: bool = False,
    dry_run: bool = False,
    caller: Any | None = None,
) -> ClassifierResult:
    if not os.getenv("OPENAI_API_KEY") and caller is None:
        return ClassifierResult(0, 0, output_path, skipped_reason="OPENAI_API_KEY missing")
    queue_df = _load_queue(queue_path)
    suggestions_df = load_ai_suggestions(output_path)
    pending = _pending_rows(queue_df, suggestions_df, force=force)
    if limit > 0:
        pending = pending.head(limit).copy()
    if pending.empty:
        return ClassifierResult(0, 0, output_path)

    model_name = model or os.getenv("AUTOSNIPER_REPAIR_AI_MODEL", "gpt-4.1-mini")
    try:
        new_suggestions = caller(pending, model=model_name) if caller is not None else _call_openai(pending, model=model_name)
    except Exception as exc:
        return ClassifierResult(
            len(pending),
            0,
            output_path,
            skipped_reason=f"{type(exc).__name__}: {str(exc)[:180]}",
        )
    for column in AI_SUGGESTION_COLUMNS:
        if column not in new_suggestions.columns:
            new_suggestions[column] = ""
    new_suggestions = new_suggestions[AI_SUGGESTION_COLUMNS]
    if dry_run:
        return ClassifierResult(len(pending), len(new_suggestions), output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if force:
        existing = suggestions_df[~suggestions_df["repair_key"].isin(set(new_suggestions["repair_key"]))].copy()
    else:
        existing = suggestions_df.copy()
    combined = new_suggestions.copy() if existing.empty else pd.concat([existing, new_suggestions], ignore_index=True)
    combined = combined.drop_duplicates(subset=["repair_key"], keep="last")
    combined.to_csv(output_path, index=False)
    return ClassifierResult(len(pending), len(new_suggestions), output_path)
