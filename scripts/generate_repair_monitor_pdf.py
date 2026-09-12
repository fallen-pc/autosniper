from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, LongTable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from shared.repair_ai_classifier import AI_SUGGESTIONS_PATH, load_ai_suggestions
from shared.repair_monitor import build_repair_monitor_rows, repair_monitor_summary
from shared.repair_review import DECISIONS_PATH, LIVE_QUEUE_PATH, latest_repair_decisions


INK = colors.HexColor("#17202A")
NAVY = colors.HexColor("#243B53")
TEAL = colors.HexColor("#0B7285")
PALE = colors.HexColor("#F5F7FA")
GRID = colors.HexColor("#BCCCDC")
MUTED = colors.HexColor("#627D98")
RED = colors.HexColor("#B42318")
AMBER = colors.HexColor("#B54708")


def _money(value: object) -> str:
    return f"${int(float(value or 0)):,.0f}"


def _paragraph(text: object, style: ParagraphStyle) -> Paragraph:
    from html import escape

    return Paragraph(escape(str(text or "")).replace("\n", "<br/>"), style)


def _result_text(row: pd.Series) -> str:
    outcome = str(row.get("outcome") or "")
    if outcome == "Priced":
        return f"{_money(row.get('low_cost'))} - {_money(row.get('high_cost'))}\nDefault {_money(row.get('default_cost'))}"
    if outcome == "Hard avoid":
        reason = str(row.get("hard_avoid_reason") or "condition risk").replace("_", " ")
        return f"AVOID\n{reason}"
    if outcome == "Needs decision":
        return "UNPRICED\nOperator decision required"
    return "No repair allowance"


def _ai_text(row: pd.Series) -> str:
    decision = str(row.get("ai_decision") or "Pending")
    canonical = str(row.get("ai_canonical_defect") or "").replace("_", " ")
    confidence = pd.to_numeric(row.get("ai_confidence", ""), errors="coerce")
    parts = [decision]
    if canonical:
        parts.append(canonical)
    if not pd.isna(confidence):
        parts.append(f"Confidence {float(confidence):.2f}")
    return "\n".join(parts)


def _page(canvas, document) -> None:  # type: ignore[no-untyped-def]
    canvas.saveState()
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 7)
    canvas.drawString(12 * mm, 7 * mm, "AutoSniper Current Repair Register")
    canvas.drawRightString(landscape(A4)[0] - 12 * mm, 7 * mm, f"Page {document.page}")
    canvas.restoreState()


def generate_pdf(rows: pd.DataFrame, output_path: Path, *, generated_at: str | None = None) -> Path:
    generated_at = generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    title = ParagraphStyle("Title", parent=styles["Title"], textColor=NAVY, fontSize=22, leading=25, spaceAfter=4)
    subtitle = ParagraphStyle("Subtitle", parent=styles["Normal"], textColor=MUTED, fontSize=9, leading=12)
    section_style = ParagraphStyle("Section", parent=styles["Heading2"], textColor=NAVY, fontSize=15, leading=18, spaceAfter=6)
    cell = ParagraphStyle("Cell", parent=styles["BodyText"], textColor=INK, fontSize=6.7, leading=8.2)
    small = ParagraphStyle("Small", parent=cell, textColor=MUTED, fontSize=6.1, leading=7.3)
    metric_value = ParagraphStyle("MetricValue", parent=styles["Normal"], alignment=TA_CENTER, textColor=TEAL, fontSize=19, leading=21)
    metric_label = ParagraphStyle("MetricLabel", parent=styles["Normal"], alignment=TA_CENTER, textColor=NAVY, fontSize=7.5, leading=9)

    document = SimpleDocTemplate(
        str(output_path),
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=13 * mm,
        title="AutoSniper Current Repair Register",
        author="AutoSniper",
    )
    summary = repair_monitor_summary(rows)
    story: list[object] = [
        Paragraph("AutoSniper Current Repair Register", title),
        Paragraph(
            f"Generated {generated_at} from the live Repair Review queue and deployed deterministic rules. "
            "Astra recommendations are advisory until an operator approves and deploys a rule.",
            subtitle,
        ),
        Spacer(1, 6 * mm),
    ]
    metric_items = [
        (summary["total"], "Current lines"),
        (summary["priced"], "Priced"),
        (summary["unpriced"], "Needs decision"),
        (summary["hard_avoid"], "Hard avoids"),
        (summary["ignored"], "No-cost context"),
    ]
    metric_table = Table(
        [[Paragraph(f"<b>{value:,}</b>", metric_value) for value, _ in metric_items], [Paragraph(label, metric_label) for _, label in metric_items]],
        colWidths=[52 * mm] * 5,
        rowHeights=[13 * mm, 8 * mm],
    )
    metric_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PALE),
                ("BOX", (0, 0), (-1, -1), 0.6, GRID),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, GRID),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.extend(
        [
            metric_table,
            Spacer(1, 6 * mm),
            Paragraph(
                "How to use this report: review Needs decision first; Hard avoid entries block a purchase; Priced entries show the reference range; ignored context carries no repair allowance.",
                subtitle,
            ),
            PageBreak(),
        ]
    )

    sections = [
        ("Needs decision", "Unpriced repairs requiring operator review", AMBER),
        ("Hard avoid", "Conditions that prevent an executable purchase recommendation", RED),
        ("Priced", "Repairs covered by the deployed pricing rules", TEAL),
        ("Ignored / no cost", "Context, features, and boilerplate with no repair allowance", MUTED),
        ("Handled / no cost", "Recognised entries with no repair allowance", MUTED),
    ]
    for section_index, (outcome, description, accent) in enumerate(sections):
        section = rows[rows["outcome"] == outcome]
        if section.empty:
            continue
        if section_index and story and not isinstance(story[-1], PageBreak):
            story.append(PageBreak())
        story.append(KeepTogether([Paragraph(f"{outcome} ({len(section):,})", section_style), Paragraph(description, subtitle), Spacer(1, 3 * mm)]))
        table_rows: list[list[object]] = [
            [
                _paragraph("Repair description", cell),
                _paragraph("Seen", cell),
                _paragraph("Current result", cell),
                _paragraph("Current repair type", cell),
                _paragraph("Astra review", cell),
            ]
        ]
        for _, row in section.iterrows():
            description_text = str(row.get("repair_item") or "")
            if row.get("unresolved_fragments"):
                description_text += f"\nUnresolved: {row.get('unresolved_fragments')}"
            table_rows.append(
                [
                    _paragraph(description_text, cell),
                    _paragraph(f"{int(row.get('occurrences', 0)):,} occurrences\n{int(row.get('listing_count', 0)):,} listings", small),
                    _paragraph(_result_text(row), cell),
                    _paragraph(str(row.get("canonical_defects") or "").replace("_", " ") or "-", small),
                    _paragraph(_ai_text(row), small),
                ]
            )
        table = LongTable(
            table_rows,
            colWidths=[88 * mm, 27 * mm, 43 * mm, 50 * mm, 53 * mm],
            repeatRows=1,
            hAlign="LEFT",
        )
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("GRID", (0, 0), (-1, -1), 0.3, GRID),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 3.5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
                    ("LINEBELOW", (0, 0), (-1, 0), 1.2, accent),
                ]
            )
        )
        story.append(table)

    story.extend(
        [
            Spacer(1, 5 * mm),
            Paragraph(
                "Reference amounts use the deployed default repair schedule. Vehicle-level valuation may adjust costs by vehicle class and condition severity. Unresolved repairs fail closed and cannot support a clean Buy.",
                subtitle,
            ),
        ]
    )
    document.build(story, onFirstPage=_page, onLaterPages=_page)
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a printable current repair register.")
    parser.add_argument("--queue", type=Path, default=LIVE_QUEUE_PATH)
    parser.add_argument("--suggestions", type=Path, default=AI_SUGGESTIONS_PATH)
    parser.add_argument("--decisions", type=Path, default=DECISIONS_PATH)
    parser.add_argument("--output", type=Path, default=Path("output/pdf/autosniper_current_repairs.pdf"))
    args = parser.parse_args()

    queue = pd.read_csv(args.queue).fillna("")
    suggestions = load_ai_suggestions(args.suggestions)
    decisions = pd.read_csv(args.decisions).fillna("") if args.decisions.exists() else pd.DataFrame()
    rows = build_repair_monitor_rows(queue, suggestions, latest_repair_decisions(decisions))
    generate_pdf(rows, args.output)
    print(f"repair_monitor_pdf={args.output} rows={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
