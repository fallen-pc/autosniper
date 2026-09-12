from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import Iterable

import pandas as pd

from shared.repair_pricing import assess_repairs, repair_fragments_to_records
from shared.repair_review import safe_text


MONITOR_OUTCOMES = ["Needs decision", "Hard avoid", "Priced", "Ignored / no cost", "Handled / no cost"]


def _identity(row: pd.Series | dict[str, object]) -> tuple[str, str]:
    getter = row.get
    return (
        safe_text(getter("repair_key")).lower(),
        safe_text(getter("repair_item")).lower(),
    )


def _latest_lookup(frame: pd.DataFrame, *, include_item: bool) -> dict[object, dict[str, object]]:
    if frame.empty or "repair_key" not in frame.columns:
        return {}
    working = frame.fillna("").copy()
    lookup: dict[object, dict[str, object]] = {}
    for _, row in working.iterrows():
        key: object = _identity(row) if include_item else safe_text(row.get("repair_key")).lower()
        lookup[key] = row.to_dict()
    return lookup


def _pipe(values: Iterable[object]) -> str:
    return " | ".join(sorted({safe_text(value) for value in values if safe_text(value)}))


def _canonical_values(value: object) -> list[str]:
    if isinstance(value, str):
        return [part.strip() for part in value.split("|") if part.strip()]
    if isinstance(value, Iterable):
        return [safe_text(part) for part in value if safe_text(part)]
    return []


def _integer(value: object) -> int:
    numeric = pd.to_numeric(value, errors="coerce")
    return 0 if pd.isna(numeric) else int(numeric)


def build_repair_monitor_rows(
    queue: pd.DataFrame,
    suggestions: pd.DataFrame | None = None,
    decisions: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Replay the current review queue through the deployed repair rules.

    Astra suggestions remain advisory. This function reports what the deterministic
    parser does now and joins the suggestion and operator-decision context beside it.
    """

    if queue.empty:
        return pd.DataFrame()
    suggestions = suggestions if suggestions is not None else pd.DataFrame()
    decisions = decisions if decisions is not None else pd.DataFrame()
    suggestion_lookup = _latest_lookup(suggestions, include_item=True)
    decision_lookup = _latest_lookup(decisions, include_item=False)
    working = queue.fillna("").drop_duplicates(subset=["repair_key"], keep="last")
    rows: list[dict[str, object]] = []

    for _, source in working.iterrows():
        repair_key = safe_text(source.get("repair_key"))
        repair_item = safe_text(source.get("repair_item"))
        assessment = assess_repairs(repair_item)
        fragments = repair_fragments_to_records(assessment)
        unresolved = [
            safe_text(fragment.get("original_text")) or safe_text(fragment.get("normalized_text"))
            for fragment in fragments
            if safe_text(fragment.get("status")).lower() == "unclassified"
        ]
        ignored = bool(fragments) and all(
            safe_text(fragment.get("status")).lower() == "ignored" for fragment in fragments
        )
        if assessment.hard_avoid:
            outcome = "Hard avoid"
        elif unresolved:
            outcome = "Needs decision"
        elif assessment.total_cost > 0:
            outcome = "Priced"
        elif ignored:
            outcome = "Ignored / no cost"
        else:
            outcome = "Handled / no cost"

        suggestion = suggestion_lookup.get((repair_key.lower(), repair_item.lower()), {})
        decision = decision_lookup.get(repair_key.lower(), {})
        canonical = _pipe(
            canonical
            for fragment in fragments
            for canonical in _canonical_values(fragment.get("canonical_defects", []))
        )
        rows.append(
            {
                "outcome": outcome,
                "repair_key": repair_key,
                "repair_item": repair_item,
                "occurrences": _integer(source.get("occurrences", 0)),
                "listing_count": _integer(source.get("listing_count", 0)),
                "default_cost": int(assessment.total_cost),
                "low_cost": int(assessment.total_cost_low),
                "high_cost": int(assessment.total_cost_high),
                "hard_avoid": bool(assessment.hard_avoid),
                "hard_avoid_reason": safe_text(assessment.hard_avoid_reason),
                "canonical_defects": canonical,
                "unresolved_fragments": " | ".join(unresolved),
                "ai_state": "Reviewed" if suggestion else "Pending",
                "ai_decision": safe_text(suggestion.get("ai_decision")),
                "ai_target_category": safe_text(suggestion.get("ai_target_category")),
                "ai_canonical_defect": safe_text(suggestion.get("ai_canonical_defect")),
                "ai_cost_model": safe_text(suggestion.get("ai_cost_model")),
                "ai_confidence": pd.to_numeric(suggestion.get("ai_confidence", ""), errors="coerce"),
                "ai_rationale": safe_text(suggestion.get("ai_rationale")),
                "operator_state": "Approved" if safe_text(decision.get("decision")) else "Not approved",
                "operator_decision": safe_text(decision.get("decision")),
                "example_vehicles": safe_text(source.get("example_vehicles")),
                "example_urls": safe_text(source.get("example_urls")),
                "source_file": safe_text(source.get("source_file")),
            }
        )

    result = pd.DataFrame(rows)
    outcome_rank = {name: index for index, name in enumerate(MONITOR_OUTCOMES)}
    result["_outcome_rank"] = result["outcome"].map(outcome_rank).fillna(len(outcome_rank))
    result.sort_values(
        ["_outcome_rank", "occurrences", "repair_item"],
        ascending=[True, False, True],
        inplace=True,
    )
    return result.drop(columns=["_outcome_rank"]).reset_index(drop=True)


def repair_monitor_summary(rows: pd.DataFrame) -> dict[str, int]:
    if rows.empty:
        return {"total": 0, "priced": 0, "unpriced": 0, "hard_avoid": 0, "ignored": 0, "ai_pending": 0}
    outcomes = rows["outcome"].value_counts().to_dict()
    return {
        "total": int(len(rows)),
        "priced": int(outcomes.get("Priced", 0)),
        "unpriced": int(outcomes.get("Needs decision", 0)),
        "hard_avoid": int(outcomes.get("Hard avoid", 0)),
        "ignored": int(outcomes.get("Ignored / no cost", 0) + outcomes.get("Handled / no cost", 0)),
        "ai_pending": int((rows["ai_state"] == "Pending").sum()),
    }


def _money(value: object) -> str:
    try:
        return f"${int(float(value)):,.0f}"
    except (TypeError, ValueError):
        return "-"


def build_printable_repair_html(rows: pd.DataFrame, *, generated_at: str | None = None) -> str:
    generated_at = generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    summary = repair_monitor_summary(rows)
    sections = ["Needs decision", "Hard avoid", "Priced", "Ignored / no cost", "Handled / no cost"]
    body: list[str] = []
    for outcome in sections:
        section = rows[rows["outcome"] == outcome]
        if section.empty:
            continue
        body.append(f"<h2>{escape(outcome)} <span>{len(section):,}</span></h2>")
        body.append("<table><thead><tr><th>Repair description</th><th>Seen</th><th>Current result</th><th>Astra review</th></tr></thead><tbody>")
        for _, row in section.iterrows():
            if outcome == "Priced":
                current = f"{_money(row['low_cost'])} - {_money(row['high_cost'])}; default {_money(row['default_cost'])}"
            elif outcome == "Hard avoid":
                current = f"Avoid: {safe_text(row.get('hard_avoid_reason')).replace('_', ' ') or 'condition risk'}"
            elif outcome == "Needs decision":
                current = f"Unpriced: {safe_text(row.get('unresolved_fragments')) or 'unresolved repair text'}"
            else:
                current = "No repair allowance"
            ai = safe_text(row.get("ai_decision")) or "Pending"
            if safe_text(row.get("ai_canonical_defect")):
                ai += f" - {safe_text(row.get('ai_canonical_defect')).replace('_', ' ')}"
            body.append(
                "<tr>"
                f"<td><strong>{escape(safe_text(row.get('repair_item')))}</strong><br><small>{escape(safe_text(row.get('canonical_defects')).replace('_', ' '))}</small></td>"
                f"<td>{int(row.get('occurrences', 0)):,}<br><small>{int(row.get('listing_count', 0)):,} listings</small></td>"
                f"<td>{escape(current)}</td>"
                f"<td>{escape(ai)}</td>"
                "</tr>"
            )
        body.append("</tbody></table>")

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>AutoSniper Current Repairs</title>
<style>
@page {{ size: A4 landscape; margin: 12mm; }}
body {{ font: 10pt Arial, sans-serif; color: #17202a; margin: 0; }}
h1 {{ margin: 0 0 4px; color: #102a43; }} .meta {{ color: #52606d; margin-bottom: 14px; }}
.summary {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; margin: 14px 0 20px; }}
.card {{ border: 1px solid #d9e2ec; border-radius: 6px; padding: 9px; background: #f8fafc; }}
.card b {{ display: block; font-size: 18pt; color: #0b7285; }}
h2 {{ color: #243b53; margin: 20px 0 7px; page-break-after: avoid; }} h2 span {{ color: #627d98; font-size: 10pt; }}
table {{ width: 100%; border-collapse: collapse; margin-bottom: 14px; }}
th {{ background: #243b53; color: white; text-align: left; padding: 6px; }}
td {{ border: 1px solid #bcccdc; padding: 5px; vertical-align: top; }}
tr:nth-child(even) {{ background: #f5f7fa; }} small {{ color: #627d98; }}
footer {{ margin-top: 14px; color: #7b8794; font-size: 8pt; }}
</style></head><body>
<h1>AutoSniper Current Repair Register</h1><div class="meta">Generated {escape(generated_at)} from the live repair queue and deployed deterministic rules.</div>
<div class="summary">
<div class="card"><b>{summary['total']:,}</b>Current lines</div>
<div class="card"><b>{summary['priced']:,}</b>Priced</div>
<div class="card"><b>{summary['unpriced']:,}</b>Needs decision</div>
<div class="card"><b>{summary['hard_avoid']:,}</b>Hard avoids</div>
<div class="card"><b>{summary['ignored']:,}</b>No-cost context</div>
</div>
{''.join(body)}
<footer>Reference repair amounts use the deployed default schedule. Vehicle-level valuation may adjust the amount by vehicle class and condition severity. Astra suggestions are advisory until an operator approves and deploys a rule.</footer>
</body></html>"""
