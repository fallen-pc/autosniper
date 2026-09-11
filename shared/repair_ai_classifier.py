from __future__ import annotations

import json
import logging
import math
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import yaml

from shared.csv_utils import CSV_READ_ERRORS
from shared.repair_review import LIVE_QUEUE_PATH, safe_text

logger = logging.getLogger(__name__)


REPORT_DIR = Path("CSV_data/reports")
AI_SUGGESTIONS_PATH = REPORT_DIR / "repair_review_ai_suggestions.csv"
DICTIONARY_PATH = Path("config/condition_dictionary_v2.yaml")
DEFAULT_MODEL = "gpt-6-astra"
# Bound cost and latency for the default 25-row advisory batch. A truncated
# response fails closed; larger manual batches should use a smaller --limit.
ASTRA_MAX_COMPLETION_TOKENS = 8192
ASTRA_TIMEOUT_SECONDS = 120.0

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
    failed: bool = False


def load_ai_suggestions(path: Path = AI_SUGGESTIONS_PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=AI_SUGGESTION_COLUMNS)
    try:
        df = pd.read_csv(path).fillna("")
    except CSV_READ_ERRORS as exc:
        logger.warning(
            "Unreadable repair AI suggestions %s (%s: %s); previous suggestions will be ignored.",
            path,
            type(exc).__name__,
            exc,
        )
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
    except (OSError, yaml.YAMLError) as exc:
        logger.warning(
            "Unreadable condition dictionary %s (%s: %s); falling back to default vocabulary.",
            path,
            type(exc).__name__,
            exc,
        )
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
    working["repair_item"] = working["repair_item"].map(safe_text)
    working = working[working["repair_key"] != ""]
    working = working.drop_duplicates(subset=["repair_key"], keep="last")
    if force or suggestions_df.empty:
        return working
    suggested_lookup = {
        (safe_text(row.get("repair_key")).lower(), safe_text(row.get("repair_item")).lower())
        for _, row in suggestions_df.iterrows()
    }
    if not suggested_lookup:
        return working

    pending = []
    for _, row in working.iterrows():
        key = safe_text(row.get("repair_key")).lower()
        item = safe_text(row.get("repair_item")).lower()
        if (key, item) not in suggested_lookup:
            pending.append(True)
        else:
            pending.append(False)
    return working[pending].copy()


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
                "Return exactly one suggestion for every supplied repair_key, preserving each key exactly. Do not add or omit keys.",
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


def _validate_repair_keys(keys: Iterable[Any], source_rows: pd.DataFrame) -> None:
    keys = list(keys)
    if any(not isinstance(key, str) or not key for key in keys):
        raise ValueError("Suggestions contain an invalid repair_key")
    if len(keys) != len(set(keys)):
        raise ValueError("Suggestions contain duplicate repair_keys")
    expected = set(source_rows["repair_key"])
    if set(keys) != expected:
        raise ValueError(
            "Suggestions must cover every requested repair_key exactly "
            f"(missing={len(expected - set(keys))}, extra={len(set(keys) - expected)})"
        )


def _coerce_suggestions(raw: Any, source_rows: pd.DataFrame, *, model: str) -> pd.DataFrame:
    if not isinstance(raw, list):
        raise ValueError("Response suggestions must be an array")
    properties = _json_schema()["schema"]["properties"]["suggestions"]["items"]["properties"]
    for item in raw:
        if not isinstance(item, dict) or set(item) != set(properties):
            raise ValueError("Suggestion fields do not match the response schema")
        for field, spec in properties.items():
            value = item[field]
            if spec["type"] == "string" and not isinstance(value, str):
                raise ValueError(f"Suggestion {field} must be a string")
            if "enum" in spec and value not in spec["enum"]:
                raise ValueError(f"Suggestion {field} is outside the allowed vocabulary")
        confidence = item["confidence"]
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(confidence)
            or not 0 <= confidence <= 1
        ):
            raise ValueError("Suggestion confidence must be a finite number between 0 and 1")
    _validate_repair_keys((item["repair_key"] for item in raw), source_rows)
    source_lookup = {
        safe_text(row.get("repair_key")): safe_text(row.get("repair_item"))
        for _, row in source_rows.iterrows()
    }
    now = datetime.now(tz=timezone.utc).isoformat()
    rows: list[dict[str, object]] = []
    for item in raw:
        repair_key = item["repair_key"]
        rows.append(
            {
                "repair_key": repair_key,
                "repair_item": source_lookup[repair_key],
                "ai_decision": item["decision"],
                "ai_target_category": item["target_category"],
                "ai_canonical_defect": safe_text(item.get("canonical_defect")),
                "ai_severity_hint": item["severity_hint"],
                "ai_cost_model": item["cost_model"],
                "ai_confidence": float(item["confidence"]),
                "ai_rationale": safe_text(item.get("rationale")),
                "model": model,
                "suggested_at": now,
            }
        )
    return pd.DataFrame(rows, columns=AI_SUGGESTION_COLUMNS)


def _call_openai(rows: pd.DataFrame, *, model: str) -> pd.DataFrame:
    from openai import OpenAI

    is_astra = model == DEFAULT_MODEL or model.startswith(f"{DEFAULT_MODEL}-")
    client = OpenAI(timeout=ASTRA_TIMEOUT_SECONDS, max_retries=1) if is_astra else OpenAI()
    request: dict[str, Any] = {
        "model": model,
        "response_format": {"type": "json_schema", "json_schema": _json_schema()},
        "messages": [
            {
                "role": "system",
                "content": "You are a conservative vehicle repair classification assistant. Output JSON only.",
            },
            {"role": "user", "content": _build_prompt(rows)},
        ],
    }
    if is_astra:
        request.update(reasoning_effort="low", max_completion_tokens=ASTRA_MAX_COMPLETION_TOKENS)
    else:
        request["temperature"] = 0
    started = time.monotonic()
    response = None
    try:
        response = client.chat.completions.create(**request)
    finally:
        usage = getattr(response, "usage", None)
        logger.info(
            "Repair AI request model=%s rows=%d elapsed_seconds=%.2f "
            "prompt_tokens=%s completion_tokens=%s cached_tokens=%s reasoning_tokens=%s",
            model,
            len(rows),
            time.monotonic() - started,
            getattr(usage, "prompt_tokens", None),
            getattr(usage, "completion_tokens", None),
            getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", None),
            getattr(getattr(usage, "completion_tokens_details", None), "reasoning_tokens", None),
        )
    if not response.choices or len(response.choices) != 1:
        raise ValueError("Expected exactly one completion choice")
    choice = response.choices[0]
    if getattr(choice.message, "refusal", None):
        raise ValueError("Model refused the repair classification request")
    if choice.finish_reason != "stop":
        raise ValueError(f"Incomplete repair classification response (finish_reason={choice.finish_reason})")
    content = choice.message.content
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Empty repair classification response")
    payload = json.loads(content)
    if not isinstance(payload, dict) or set(payload) != {"suggestions"}:
        raise ValueError("Response must contain only the suggestions array")
    return _coerce_suggestions(payload["suggestions"], rows, model=model)


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

    model_name = model or os.getenv("AUTOSNIPER_REPAIR_AI_MODEL") or DEFAULT_MODEL
    if dry_run:
        return ClassifierResult(len(pending), 0, output_path, skipped_reason="dry_run: classifier call skipped")
    try:
        new_suggestions = caller(pending, model=model_name) if caller is not None else _call_openai(pending, model=model_name)
        if not isinstance(new_suggestions, pd.DataFrame) or "repair_key" not in new_suggestions:
            raise ValueError("Classifier must return suggestions with repair_keys")
        _validate_repair_keys(new_suggestions["repair_key"], pending)
    except Exception as exc:  # noqa: BLE001 - reported to the caller via skipped_reason
        logger.error("Repair AI classification call failed (%s: %s).", type(exc).__name__, exc)
        return ClassifierResult(
            len(pending),
            0,
            output_path,
            skipped_reason=f"{type(exc).__name__}: {str(exc)[:180]}",
            failed=True,
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
