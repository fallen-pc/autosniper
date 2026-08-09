"""Generate a current vehicle-tag and repair-classification reference PDF."""

from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Flowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "pdf" / "classification_reference.pdf"

NAVY = colors.HexColor("#17324D")
BLUE = colors.HexColor("#2F6B9A")
PALE_BLUE = colors.HexColor("#EAF3F9")
GREEN = colors.HexColor("#2F7D5A")
PALE_GREEN = colors.HexColor("#EAF6EF")
AMBER = colors.HexColor("#B06D16")
PALE_AMBER = colors.HexColor("#FFF3DD")
RED = colors.HexColor("#A43D3D")
PALE_RED = colors.HexColor("#FBEAEA")
GREY = colors.HexColor("#5C6670")
PALE_GREY = colors.HexColor("#F1F3F5")
GRID = colors.HexColor("#CBD3DA")


def read_csv(relative: str) -> list[dict[str, str]]:
    with (ROOT / relative).open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_condition_yaml(relative: str) -> tuple[list[str], list[dict[str, str]]]:
    """Parse the deliberately flat parts of condition_dictionary_v2.yaml."""
    text = (ROOT / relative).read_text(encoding="utf-8")
    clusters: list[str] = []
    entries: list[dict[str, str]] = []
    section = ""
    current: dict[str, str] | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if line == "repair_clusters:":
            section = "clusters"
            continue
        if line == "entries:":
            section = "entries"
            continue
        if section == "clusters" and line.startswith("- "):
            clusters.append(line[2:].strip().strip('"'))
            continue
        if section != "entries":
            continue
        if line.startswith("- "):
            if current:
                entries.append(current)
            current = {}
            line = line[2:]
        if current is not None and ":" in line:
            key, value = line.split(":", 1)
            current[key.strip()] = value.strip().strip('"')
    if current:
        entries.append(current)
    return clusters, entries


def friendly(value: str) -> str:
    return re.sub(r"[-_]+", " ", str(value or "")).strip().title()


def shortened_tag(tag: str) -> str:
    return str(tag or "").replace("_", " / ")


def vehicle_variant(row: dict[str, str]) -> str:
    """Derive the human-readable variant left after known identity fields."""
    tag_parts = str(row.get("base_curve_tag", "")).split("_")
    known = [
        row.get("make", ""),
        row.get("model", ""),
        row.get("body", ""),
        row.get("fuel", ""),
        row.get("transmission", ""),
        row.get("series", ""),
    ]
    remaining = list(tag_parts)
    for value in known:
        normalized = str(value or "").strip().lower()
        if normalized in remaining:
            remaining.remove(normalized)
    variant = " ".join(remaining).strip()
    return friendly(variant) if variant else "Base / grouped model"


class FlowDiagram(Flowable):
    def __init__(self, labels: list[tuple[str, str]], width: float = 257 * mm):
        super().__init__()
        self.labels = labels
        self.width = width
        self.height = 31 * mm

    def draw(self) -> None:
        canvas = self.canv
        count = len(self.labels)
        gap = 5 * mm
        box_w = (self.width - gap * (count - 1)) / count
        box_h = 22 * mm
        y = 5 * mm
        for index, (title, detail) in enumerate(self.labels):
            x = index * (box_w + gap)
            canvas.setFillColor(PALE_BLUE if index < count - 1 else PALE_GREEN)
            canvas.setStrokeColor(BLUE if index < count - 1 else GREEN)
            canvas.roundRect(x, y, box_w, box_h, 3 * mm, fill=1, stroke=1)
            canvas.setFillColor(NAVY)
            canvas.setFont("Helvetica-Bold", 8.5)
            canvas.drawCentredString(x + box_w / 2, y + 14.5 * mm, title)
            canvas.setFillColor(GREY)
            canvas.setFont("Helvetica", 6.8)
            lines = _wrap_canvas(detail, 34)
            for row, text in enumerate(lines[:3]):
                canvas.drawCentredString(x + box_w / 2, y + (10.5 - row * 3.4) * mm, text)
            if index < count - 1:
                start = x + box_w
                end = start + gap
                mid_y = y + box_h / 2
                canvas.setStrokeColor(GREY)
                canvas.line(start + 1 * mm, mid_y, end - 1.5 * mm, mid_y)
                canvas.setFillColor(GREY)
                canvas.drawString(end - 2.5 * mm, mid_y - 1.4 * mm, ">")


def _wrap_canvas(text: str, limit: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > limit:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def make_styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "Title",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=24,
            leading=28,
            textColor=NAVY,
            alignment=TA_LEFT,
            spaceAfter=5 * mm,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle",
            parent=base["Normal"],
            fontSize=11,
            leading=15,
            textColor=GREY,
            spaceAfter=5 * mm,
        ),
        "h1": ParagraphStyle(
            "H1",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=17,
            leading=20,
            textColor=NAVY,
            spaceBefore=2 * mm,
            spaceAfter=3 * mm,
        ),
        "h2": ParagraphStyle(
            "H2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            textColor=BLUE,
            spaceBefore=3 * mm,
            spaceAfter=2 * mm,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["BodyText"],
            fontSize=8.5,
            leading=11.5,
            textColor=colors.HexColor("#26323C"),
            spaceAfter=2 * mm,
        ),
        "small": ParagraphStyle(
            "Small",
            parent=base["BodyText"],
            fontSize=6.9,
            leading=8.7,
            textColor=colors.HexColor("#26323C"),
        ),
        "small_muted": ParagraphStyle(
            "SmallMuted",
            parent=base["BodyText"],
            fontSize=6.5,
            leading=8,
            textColor=GREY,
        ),
        "metric": ParagraphStyle(
            "Metric",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=17,
            textColor=NAVY,
            alignment=TA_CENTER,
        ),
        "metric_label": ParagraphStyle(
            "MetricLabel",
            parent=base["BodyText"],
            fontSize=7,
            leading=9,
            textColor=GREY,
            alignment=TA_CENTER,
        ),
    }


def p(text: object, style) -> Paragraph:
    safe = str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return Paragraph(safe, style)


def metric_table(items: list[tuple[str, str]], styles) -> Table:
    cells = [[p(value, styles["metric"]), p(label, styles["metric_label"])] for value, label in items]
    table = Table([cells], colWidths=[257 * mm / len(cells)], rowHeights=[26 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PALE_BLUE),
                ("BOX", (0, 0), (-1, -1), 0.6, GRID),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.white),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
            ]
        )
    )
    return table


def data_table(
    headers: list[str],
    rows: list[list[object]],
    widths: list[float],
    styles,
    header_color=BLUE,
) -> Table:
    content = [[p(head, styles["small"],) for head in headers]]
    content.extend([[p(cell, styles["small"]) for cell in row] for row in rows])
    table = Table(content, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), header_color),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.35, GRID),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE_GREY]),
                ("LEFTPADDING", (0, 0), (-1, -1), 1.4 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 1.4 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 1.1 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.1 * mm),
            ]
        )
    )
    return table


def add_page_number(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(GRID)
    canvas.line(20 * mm, 13 * mm, 277 * mm, 13 * mm)
    canvas.setFillColor(GREY)
    canvas.setFont("Helvetica", 7)
    canvas.drawString(20 * mm, 8 * mm, "AutoSniper classification reference")
    canvas.drawRightString(277 * mm, 8 * mm, f"Page {doc.page}")
    canvas.restoreState()


def build_pdf() -> Path:
    curves = read_csv("CSV_data/restricted/curves.csv")
    groups = read_csv("config/curve_groups_v2.csv")
    aliases = read_csv("config/curve_aliases.csv")
    universe = read_csv("config/supported_curve_universe_v1.csv")
    restricted = read_csv("CSV_data/restricted/restricted_group_map.csv")
    decisions = read_csv("CSV_data/reports/repair_review_decisions.csv")
    queue = read_csv("CSV_data/reports/repair_review_live_queue.csv")
    schedule = read_csv("CSV_data/reports/repair_pricing_schedule.csv")
    clusters, repair_entries = parse_condition_yaml("config/condition_dictionary_v2.yaml")

    curve_tags = sorted({row["canonical_tag"] for row in curves if row.get("canonical_tag")})
    tags_by_make: dict[str, list[str]] = defaultdict(list)
    for tag in curve_tags:
        tags_by_make[tag.split("_", 1)[0]].append(tag)
    reason_counts = Counter(row.get("reason_code", "") for row in restricted)
    ok_count = reason_counts.get("[OK]", 0)
    unclassified_count = sum(value for key, value in reason_counts.items() if key != "[OK]")
    category_counts = Counter(row.get("category", "") for row in repair_entries)
    defect_by_category: dict[str, set[str]] = defaultdict(set)
    for row in repair_entries:
        defect_by_category[row.get("category", "")].add(row.get("canonical_defect", ""))
    decision_counts = Counter(row.get("decision", "") for row in decisions)
    runtime_decisions = [
        row for row in decisions if "runtime-effective" in row.get("notes", "").lower()
    ]
    queue_counts = Counter(row.get("status", "") for row in queue)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    styles = make_styles()
    doc = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=landscape(A4),
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=16 * mm,
        bottomMargin=18 * mm,
        title="AutoSniper Vehicle Tags and Repair Classification Reference",
        author="AutoSniper",
    )
    story: list[object] = []

    story += [
        Spacer(1, 16 * mm),
        p("AutoSniper Classification Reference", styles["title"]),
        p(
            "Current vehicle-tag and repair-group logic, generated directly from the governed CSV, YAML, and review files.",
            styles["subtitle"],
        ),
        metric_table(
            [
                (str(len(curve_tags)), "active curve / base tags"),
                (str(len(groups)), "explicit tag-to-curve mappings"),
                (f"{ok_count:,}", "classified restricted records"),
                (str(len(repair_entries)), "repair pattern rules"),
                (str(len({r.get('canonical_defect') for r in repair_entries})), "named repair defects"),
                (str(len(queue)), "live repair queue fragments"),
            ],
            styles,
        ),
        Spacer(1, 7 * mm),
        p("How to read this reference", styles["h1"]),
        p(
            "A vehicle can be parsed successfully but still be out of the supported buying universe. "
            "Likewise, a repair phrase can be recognized without being priceable: mechanical or structural "
            "hard-stop rules intentionally produce Avoid, while unresolved fragments remain Review blockers.",
            styles["body"],
        ),
        p(
            f"Snapshot generated {datetime.now().astimezone().strftime('%d %B %Y, %H:%M %Z')}. "
            "Regenerate after tag, curve, repair-dictionary, pricing-schedule, or review-decision changes.",
            styles["small_muted"],
        ),
        PageBreak(),
        p("1. Vehicle tag classification", styles["h1"]),
        p(
            "The tag path separates vehicle identity from curve ownership. The parsed canonical tag is checked "
            "against allowed variants, mapped to a governed base curve, then checked for year and kilometre coverage.",
            styles["body"],
        ),
        FlowDiagram(
            [
                ("Parse identity", "Make, model, badge, fuel, transmission, body and series"),
                ("Build canonical tag", "Seven normalized fields joined into one identity"),
                ("Check eligibility", "Allowed variant and supported universe checks"),
                ("Resolve base curve", "V2 group mapping first, alias fallback where defined"),
                ("Check coverage", "Saved curve tag plus supported year and kilometre bucket"),
                ("Classify", "OK or one explicit reason code"),
            ]
        ),
        Spacer(1, 4 * mm),
        metric_table(
            [
                (str(len(universe)), "supported live base curves"),
                (str(len(groups)), "active V2 match mappings"),
                (str(len(aliases)), "legacy aliases"),
                (f"{len(restricted):,}", "restricted records audited"),
                (f"{ok_count:,}", "OK"),
                (f"{unclassified_count:,}", "not classified into a live curve"),
            ],
            styles,
        ),
        Spacer(1, 5 * mm),
        p("Classification outcomes in the current restricted map", styles["h2"]),
        data_table(
            ["Outcome", "Records", "Meaning"],
            [
                [
                    key.strip("[]").replace("_", " ").title(),
                    f"{count:,}",
                    {
                        "[OK]": "Resolved to a supported canonical curve tag.",
                        "[OUT_OF_SCOPE]": "Vehicle family is outside the governed universe.",
                        "[DISALLOWED_VARIANT]": "Family is known, but this badge/body/fuel/series combination is not allowed.",
                        "[OUT_OF_SCOPE_YEAR]": "Tag is known, but the year is outside current coverage.",
                        "[AMBIG_BADGE]": "Badge could not be resolved safely.",
                        "[AMBIG_FUEL]": "Fuel type could not be resolved safely.",
                        "[AMBIG_TRANS]": "Transmission could not be resolved safely.",
                        "[BAD_PARSE]": "Required identity fields could not be parsed.",
                        "[NON_VEHICLE]": "Source row is not a vehicle listing.",
                    }.get(key, "Explicit classifier outcome."),
                ]
                for key, count in reason_counts.most_common()
            ],
            [55 * mm, 26 * mm, 176 * mm],
            styles,
        ),
        PageBreak(),
        p("Current base vehicle groups", styles["h1"]),
        p(
            "Each row is one vehicle group that currently owns a saved price grid. The plain-English vehicle name "
            "is the main reference. Raw code tags are kept out of this section and remain available in the later "
            "technical mapping appendix.",
            styles["body"],
        ),
    ]

    universe_rows = sorted(
        universe,
        key=lambda row: (
            row.get("make", ""),
            row.get("model", ""),
            vehicle_variant(row),
            row.get("series", ""),
        ),
    )
    story.append(
        data_table(
            ["Vehicle", "Variant / grade", "Series", "Body", "Fuel", "Gearbox"],
            [
                [
                    f"{friendly(row.get('make', ''))} {friendly(row.get('model', ''))}",
                    vehicle_variant(row),
                    str(row.get("series", "")).upper(),
                    friendly(row.get("body", "")),
                    friendly(row.get("fuel", "")),
                    friendly(row.get("transmission", "")),
                ]
                for row in universe_rows
            ],
            [56 * mm, 60 * mm, 38 * mm, 34 * mm, 32 * mm, 37 * mm],
            styles,
        )
    )

    story += [
        PageBreak(),
        p("Explicit vehicle tag-to-curve mappings", styles["h1"]),
        p(
            "Each row below says that a recognized match tag uses the named base curve. This is classification "
            "alignment only; it does not change the saved curve prices.",
            styles["body"],
        ),
        data_table(
            ["Recognized match tag", "Resolved base curve tag", "Reason"],
            [
                [shortened_tag(row["match_tag"]), shortened_tag(row["base_curve_tag"]), row.get("reason", "")]
                for row in groups
            ],
            [91 * mm, 91 * mm, 75 * mm],
            styles,
        ),
        PageBreak(),
        p("2. Repair classification", styles["h1"]),
        p(
            "Condition text is split into fragments. Explicit runtime-effective operator decisions take precedence, "
            "then hard-stop rules and the V2 dictionary are applied. Recognized priceable items are costed; anything "
            "unresolved is queued and blocks a clean Buy until reviewed.",
            styles["body"],
        ),
        FlowDiagram(
            [
                ("Split condition text", "Normalize punctuation and isolate individual fragments"),
                ("Apply saved decisions", "Runtime-effective human decisions override generic matches"),
                ("Check hard stops", "Mechanical and structural hazards force Avoid"),
                ("Match V2 rules", "Pattern becomes canonical defect, category and severity"),
                ("Price or ignore", "Schedule cost, panel model, risk, context or boilerplate"),
                ("Final state", "Costed, hard avoid, or unresolved Review queue"),
            ]
        ),
        Spacer(1, 4 * mm),
        metric_table(
            [
                (str(len(repair_entries)), "V2 pattern entries"),
                (str(len({r.get('canonical_defect') for r in repair_entries})), "unique canonical defects"),
                (str(len(schedule)), "priced schedule rows"),
                (f"{len(decisions):,}", "saved operator decisions"),
                (str(len(runtime_decisions)), "runtime-effective decisions"),
                (str(len(queue)), "current queue fragments"),
            ],
            styles,
        ),
        Spacer(1, 5 * mm),
        p("Repair outcomes", styles["h2"]),
        data_table(
            ["Path", "Result", "Buying consequence"],
            [
                ["Mechanical hard stop", "MECHANICAL pill and conservative hard-stop estimate", "Avoid"],
                ["Structural hard stop", "STRUCTURAL pill and conservative hard-stop estimate", "Avoid"],
                ["Priceable defect", "Low/high repair cost from schedule or costing model", "Deduct pessimistic cost from bid logic"],
                ["Context / boilerplate / feature leak", "Recognized with no repair charge", "Does not create a repair"],
                ["Usage risk", "Risk signal retained", "Review in context; not silently discarded"],
                ["Unclassified fragment", "Written to Repair Review queue", "Review or Avoid (unresolved repairs); no clean Buy"],
            ],
            [62 * mm, 99 * mm, 96 * mm],
            styles,
        ),
        PageBreak(),
        p("Repair categories and named defects", styles["h1"]),
        p(
            "The dictionary currently declares seven categories. Repair clusters are broader intended groupings; "
            "the actual live matcher is driven by the canonical defects and rule entries listed here.",
            styles["body"],
        ),
        p("Declared clusters: " + ", ".join(friendly(item) for item in clusters), styles["body"]),
        data_table(
            ["Category", "Rules", "Unique defects", "Canonical defects"],
            [
                [
                    friendly(category),
                    str(category_counts[category]),
                    str(len(defect_by_category[category])),
                    ", ".join(friendly(item) for item in sorted(defect_by_category[category]) if item),
                ]
                for category in sorted(category_counts)
            ],
            [35 * mm, 18 * mm, 25 * mm, 179 * mm],
            styles,
        ),
        Spacer(1, 5 * mm),
        p("Live queue status", styles["h2"]),
        data_table(
            ["Queue status", "Fragments", "Interpretation"],
            [
                [friendly(status), str(count), {
                    "unclassified": "No accepted rule or effective decision yet.",
                    "hard_avoid": "The fragment itself triggered a hard stop.",
                    "not_assessed_after_hard_avoid": "Another fragment already stopped the vehicle, so this one was not priced.",
                }.get(status, "Recorded review state.")]
                for status, count in queue_counts.most_common()
            ],
            [62 * mm, 25 * mm, 170 * mm],
            styles,
        ),
        PageBreak(),
        p("Repair rule catalogue", styles["h1"]),
        p(
            "Patterns are summarized for audit readability. A raw phrase is an exact phrase-style rule; a regex "
            "is a flexible text match. Severity is a hint used by the repair engine, not a standalone verdict.",
            styles["body"],
        ),
        data_table(
            ["Category", "Canonical defect", "Severity", "Rule type", "Phrase or pattern"],
            [
                [
                    friendly(row.get("category", "")),
                    friendly(row.get("canonical_defect", "")),
                    friendly(row.get("severity_hint", "")),
                    "Regex" if row.get("pattern") else "Phrase",
                    row.get("pattern") or row.get("raw_phrase", ""),
                ]
                for row in repair_entries
            ],
            [28 * mm, 49 * mm, 20 * mm, 18 * mm, 142 * mm],
            styles,
        ),
        PageBreak(),
        p("Repair pricing schedule", styles["h1"]),
        p(
            "The schedule is evidence-backed and may contain more than one vehicle class for a defect. "
            "Low and high estimates form the uncertainty range; bid logic uses the pessimistic repair side.",
            styles["body"],
        ),
        data_table(
            ["Defect", "Category", "Class", "Method", "Default", "Low", "High", "Confidence", "Evidence"],
            [
                [
                    friendly(row.get("canonical_defect", "")),
                    friendly(row.get("category", "")),
                    friendly(row.get("vehicle_class", "")),
                    friendly(row.get("pricing_method", "")),
                    f"${float(row.get('default_estimate') or 0):,.0f}",
                    f"${float(row.get('low_estimate') or 0):,.0f}",
                    f"${float(row.get('high_estimate') or 0):,.0f}",
                    friendly(row.get("confidence", "")),
                    row.get("evidence_source", ""),
                ]
                for row in schedule
            ],
            [43 * mm, 24 * mm, 22 * mm, 31 * mm, 18 * mm, 16 * mm, 16 * mm, 22 * mm, 65 * mm],
            styles,
        ),
        PageBreak(),
        p("Operator review decisions", styles["h1"]),
        p(
            "All saved decisions are retained for audit history. Only rows marked runtime-effective in notes "
            "currently alter repair assessment. The latest normalized decision for a fragment wins.",
            styles["body"],
        ),
        data_table(
            ["Decision", "Saved rows", "Current behavior"],
            [
                [
                    decision,
                    f"{count:,}",
                    {
                        "Add dictionary rule": "Recognize as a repair; cost model decides hard stop, panel, replacement, or glass.",
                        "Mark context fragment": "Treat as context with no standalone repair charge.",
                        "Ignore as boilerplate": "Recognize and ignore as non-repair text.",
                        "Leave unclassified": "Keep unresolved for later review.",
                        "Mark feature-list leak": "Treat equipment-list text as non-repair.",
                        "Mark usage risk": "Retain usage risk without inventing a repair charge.",
                    }.get(decision, "Saved operator classification."),
                ]
                for decision, count in decision_counts.most_common()
            ],
            [62 * mm, 28 * mm, 167 * mm],
            styles,
        ),
        Spacer(1, 5 * mm),
        p("Runtime-effective decision breakdown", styles["h2"]),
        data_table(
            ["Decision", "Cost model", "Rows"],
            [
                [decision, cost_model or "(blank)", str(count)]
                for (decision, cost_model), count in Counter(
                    (row.get("decision", ""), row.get("cost_model", "")) for row in runtime_decisions
                ).most_common()
            ],
            [85 * mm, 85 * mm, 30 * mm],
            styles,
        ),
        Spacer(1, 6 * mm),
        p("Source-of-truth files", styles["h2"]),
        data_table(
            ["Purpose", "File"],
            [
                ["Saved curve grids", "CSV_data/restricted/curves.csv"],
                ["Tag-to-base-curve mapping", "config/curve_groups_v2.csv"],
                ["Supported base-curve universe", "config/supported_curve_universe_v1.csv"],
                ["Restricted classification audit", "CSV_data/restricted/restricted_group_map.csv"],
                ["Repair matcher rules", "config/condition_dictionary_v2.yaml"],
                ["Repair pricing evidence", "CSV_data/reports/repair_pricing_schedule.csv"],
                ["Human review decisions", "CSV_data/reports/repair_review_decisions.csv"],
                ["Current unresolved review surface", "CSV_data/reports/repair_review_live_queue.csv"],
            ],
            [85 * mm, 172 * mm],
            styles,
        ),
    ]

    doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    return OUTPUT


if __name__ == "__main__":
    print(build_pdf())
