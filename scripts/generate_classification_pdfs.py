"""Generate separate current vehicle and repair classification PDFs."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, SimpleDocTemplate, Spacer

from generate_classification_reference_pdf import (
    FlowDiagram,
    ROOT,
    add_page_number,
    data_table,
    friendly,
    make_styles,
    metric_table,
    p,
    parse_condition_yaml,
    read_csv,
    shortened_tag,
    vehicle_variant,
)


OUTPUT_DIR = ROOT / "output" / "pdf"
VEHICLE_OUTPUT = OUTPUT_DIR / "vehicle_classifications.pdf"
REPAIR_OUTPUT = OUTPUT_DIR / "repair_classifications.pdf"


def _document(path: Path, title: str) -> SimpleDocTemplate:
    return SimpleDocTemplate(
        str(path),
        pagesize=landscape(A4),
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=16 * mm,
        bottomMargin=18 * mm,
        title=title,
        author="AutoSniper",
    )


def build_vehicle_pdf() -> Path:
    curves = read_csv("CSV_data/restricted/curves.csv")
    groups = read_csv("config/curve_groups_v2.csv")
    aliases = read_csv("config/curve_aliases.csv")
    universe = read_csv("config/supported_curve_universe_v1.csv")
    restricted = read_csv("CSV_data/restricted/restricted_group_map.csv")

    curve_tags = {row["canonical_tag"] for row in curves if row.get("canonical_tag")}
    reason_counts = Counter(row.get("reason_code", "") for row in restricted)
    ok_count = reason_counts.get("[OK]", 0)
    not_live_count = len(restricted) - ok_count
    styles = make_styles()
    generated = datetime.now().astimezone().strftime("%d %B %Y, %H:%M %Z")

    universe_rows = sorted(
        universe,
        key=lambda row: (
            row.get("make", ""),
            row.get("model", ""),
            vehicle_variant(row),
            row.get("series", ""),
        ),
    )

    story = [
        Spacer(1, 13 * mm),
        p("AutoSniper Vehicle Classifications", styles["title"]),
        p(
            "Current vehicle groups, classification flow and tag-to-curve mappings generated from the governed vehicle files.",
            styles["subtitle"],
        ),
        metric_table(
            [
                (str(len(universe)), "supported base vehicle groups"),
                (str(len(curve_tags)), "base tags with saved curve rows"),
                (str(len(groups)), "explicit tag-to-curve mappings"),
                (str(len(aliases)), "legacy aliases"),
                (f"{ok_count:,}", "classified restricted records"),
                (f"{not_live_count:,}", "records outside a live curve"),
            ],
            styles,
        ),
        Spacer(1, 7 * mm),
        p("How vehicle classification works", styles["h1"]),
        FlowDiagram(
            [
                ("Parse identity", "Make, model, badge, fuel, transmission, body and series"),
                ("Build canonical tag", "Normalize the seven vehicle identity fields"),
                ("Check eligibility", "Allowed variant and supported-universe checks"),
                ("Resolve base group", "V2 group mapping first, then any legacy alias"),
                ("Check curve coverage", "Saved group, year and kilometre bucket"),
                ("Classify", "OK or one explicit exclusion reason"),
            ]
        ),
        Spacer(1, 3 * mm),
        p(
            "A vehicle may parse correctly yet remain outside the supported buying universe. A recognized tag also needs a governed base group and saved year/kilometre coverage before it is usable for valuation.",
            styles["body"],
        ),
        p(f"Snapshot generated {generated}.", styles["small_muted"]),
        PageBreak(),
        p("Current classification outcomes", styles["h1"]),
        data_table(
            ["Outcome", "Records", "Meaning"],
            [
                [
                    key.strip("[]").replace("_", " ").title(),
                    f"{count:,}",
                    {
                        "[OK]": "Resolved to a supported vehicle group with a live curve.",
                        "[OUT_OF_SCOPE]": "Vehicle family is outside the governed universe.",
                        "[DISALLOWED_VARIANT]": "Known family, but this grade/body/fuel/series combination is not allowed.",
                        "[OUT_OF_SCOPE_YEAR]": "Known group, but the year is outside saved coverage.",
                        "[AMBIG_BADGE]": "Variant or badge could not be resolved safely.",
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
            "Each row is one plain-English vehicle group that currently owns a saved price grid. Raw code tags are kept in the later technical mapping appendix.",
            styles["body"],
        ),
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
        ),
        PageBreak(),
        p("Technical tag-to-group mappings", styles["h1"]),
        p(
            "This appendix records which recognized tag resolves to which base curve. It documents identity alignment only and does not alter saved prices.",
            styles["body"],
        ),
        data_table(
            ["Recognized source tag", "Resolved base group tag", "Why they are grouped"],
            [
                [shortened_tag(row["match_tag"]), shortened_tag(row["base_curve_tag"]), row.get("reason", "")]
                for row in groups
            ],
            [91 * mm, 91 * mm, 75 * mm],
            styles,
        ),
        PageBreak(),
        p("Vehicle classification source files", styles["h1"]),
        data_table(
            ["Purpose", "Current file"],
            [
                ["Saved resale curve grids", "CSV_data/restricted/curves.csv"],
                ["Recognized-tag to base-group mapping", "config/curve_groups_v2.csv"],
                ["Supported base vehicle universe", "config/supported_curve_universe_v1.csv"],
                ["Legacy compatibility aliases", "config/curve_aliases.csv"],
                ["Restricted classification audit", "CSV_data/restricted/restricted_group_map.csv"],
                ["Classifier implementation", "shared/canonical_tagging.py"],
            ],
            [92 * mm, 165 * mm],
            styles,
        ),
    ]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _document(VEHICLE_OUTPUT, "AutoSniper Vehicle Classifications").build(
        story, onFirstPage=add_page_number, onLaterPages=add_page_number
    )
    return VEHICLE_OUTPUT


def build_repair_pdf() -> Path:
    decisions = read_csv("CSV_data/reports/repair_review_decisions.csv")
    queue = read_csv("CSV_data/reports/repair_review_live_queue.csv")
    schedule = read_csv("CSV_data/reports/repair_pricing_schedule.csv")
    clusters, entries = parse_condition_yaml("config/condition_dictionary_v2.yaml")

    category_counts = Counter(row.get("category", "") for row in entries)
    defects: dict[str, set[str]] = defaultdict(set)
    for row in entries:
        defects[row.get("category", "")].add(row.get("canonical_defect", ""))
    decision_counts = Counter(row.get("decision", "") for row in decisions)
    runtime_decisions = [row for row in decisions if "runtime-effective" in row.get("notes", "").lower()]
    queue_counts = Counter(row.get("status", "") for row in queue)
    unique_defects = {row.get("canonical_defect") for row in entries if row.get("canonical_defect")}
    styles = make_styles()
    generated = datetime.now().astimezone().strftime("%d %B %Y, %H:%M %Z")

    story = [
        Spacer(1, 13 * mm),
        p("AutoSniper Repair Classifications", styles["title"]),
        p(
            "Current repair groups, matching rules, prices and review outcomes generated from the governed repair files.",
            styles["subtitle"],
        ),
        metric_table(
            [
                (str(len(entries)), "repair pattern rules"),
                (str(len(unique_defects)), "named repair defects"),
                (str(len(schedule)), "pricing schedule rows"),
                (f"{len(decisions):,}", "saved review decisions"),
                (str(len(runtime_decisions)), "runtime-effective decisions"),
                (str(len(queue)), "current queue fragments"),
            ],
            styles,
        ),
        Spacer(1, 7 * mm),
        p("How repair classification works", styles["h1"]),
        FlowDiagram(
            [
                ("Split condition text", "Normalize punctuation and isolate fragments"),
                ("Apply saved decisions", "Effective human decisions override generic matches"),
                ("Check hard stops", "Mechanical and structural hazards force Avoid"),
                ("Match repair rules", "Assign canonical defect, category and severity"),
                ("Price or ignore", "Schedule cost, panel model, risk or boilerplate"),
                ("Final state", "Costed, hard avoid or unresolved Review queue"),
            ]
        ),
        Spacer(1, 3 * mm),
        p(
            "Unresolved repair fragments block a clean Buy until they are classified and repriced. Context, boilerplate and feature-list text can be recognized without creating a repair charge.",
            styles["body"],
        ),
        p(f"Snapshot generated {generated}.", styles["small_muted"]),
        PageBreak(),
        p("Repair outcomes", styles["h1"]),
        data_table(
            ["Classification path", "System result", "Buying consequence"],
            [
                ["Mechanical hard stop", "MECHANICAL risk and conservative hard-stop estimate", "Avoid"],
                ["Structural hard stop", "STRUCTURAL risk and conservative hard-stop estimate", "Avoid"],
                ["Priceable defect", "Low/high cost from the schedule or costing model", "Pessimistic cost is deducted in bid logic"],
                ["Context / boilerplate / feature leak", "Recognized with no repair charge", "Does not create a repair"],
                ["Usage risk", "Risk signal is retained", "Review in vehicle context"],
                ["Unclassified fragment", "Written to Repair Review queue", "Review or Avoid (unresolved repairs); no clean Buy"],
            ],
            [65 * mm, 98 * mm, 94 * mm],
            styles,
        ),
        Spacer(1, 5 * mm),
        p("Current live queue status", styles["h2"]),
        data_table(
            ["Queue status", "Fragments", "Meaning"],
            [
                [
                    friendly(status),
                    str(count),
                    {
                        "unclassified": "No accepted rule or effective decision yet.",
                        "hard_avoid": "This fragment triggered a hard stop.",
                        "not_assessed_after_hard_avoid": "Another fragment already stopped the vehicle, so this one was not priced.",
                    }.get(status, "Recorded review state."),
                ]
                for status, count in queue_counts.most_common()
            ],
            [62 * mm, 25 * mm, 170 * mm],
            styles,
        ),
        PageBreak(),
        p("Repair groups and named defects", styles["h1"]),
        p(
            "The categories below are the live matching groups. Declared clusters are broader planning labels; canonical defects drive the actual matcher and pricing path.",
            styles["body"],
        ),
        p("Declared clusters: " + ", ".join(friendly(item) for item in clusters), styles["body"]),
        data_table(
            ["Repair group", "Rules", "Named defects", "Defects currently recognized"],
            [
                [
                    friendly(category),
                    str(category_counts[category]),
                    str(len(defects[category])),
                    ", ".join(friendly(item) for item in sorted(defects[category]) if item),
                ]
                for category in sorted(category_counts)
            ],
            [35 * mm, 18 * mm, 26 * mm, 178 * mm],
            styles,
        ),
        PageBreak(),
        p("Repair rule catalogue", styles["h1"]),
        p(
            "Phrase rules match named wording; regex rules recognize flexible wording. Severity is an input hint, not a verdict by itself.",
            styles["body"],
        ),
        data_table(
            ["Group", "Canonical defect", "Severity", "Rule type", "Phrase or matching pattern"],
            [
                [
                    friendly(row.get("category", "")),
                    friendly(row.get("canonical_defect", "")),
                    friendly(row.get("severity_hint", "")),
                    "Regex" if row.get("pattern") else "Phrase",
                    row.get("pattern") or row.get("raw_phrase", ""),
                ]
                for row in entries
            ],
            [28 * mm, 49 * mm, 20 * mm, 18 * mm, 142 * mm],
            styles,
        ),
        PageBreak(),
        p("Repair pricing schedule", styles["h1"]),
        p(
            "Low and high values represent the repair uncertainty range. The pessimistic repair side is used for bid deductions.",
            styles["body"],
        ),
        data_table(
            ["Defect", "Group", "Class", "Method", "Default", "Low", "High", "Confidence", "Evidence"],
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
            "All decisions remain in the audit history. Only decisions marked runtime-effective currently alter repair assessment; the latest normalized decision for a fragment wins.",
            styles["body"],
        ),
        data_table(
            ["Decision", "Saved rows", "Current behavior"],
            [
                [
                    decision,
                    f"{count:,}",
                    {
                        "Add dictionary rule": "Recognize as a repair; its cost model decides hard stop, panel, replacement or glass.",
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
        p("Repair classification source files", styles["h2"]),
        data_table(
            ["Purpose", "Current file"],
            [
                ["Repair matching rules", "config/condition_dictionary_v2.yaml"],
                ["Repair pricing evidence", "CSV_data/reports/repair_pricing_schedule.csv"],
                ["Human review decisions", "CSV_data/reports/repair_review_decisions.csv"],
                ["Current unresolved review surface", "CSV_data/reports/repair_review_live_queue.csv"],
                ["Repair engine", "shared/repair_pricing.py"],
                ["Queue and decision normalization", "shared/repair_review.py"],
            ],
            [92 * mm, 165 * mm],
            styles,
        ),
    ]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _document(REPAIR_OUTPUT, "AutoSniper Repair Classifications").build(
        story, onFirstPage=add_page_number, onLaterPages=add_page_number
    )
    return REPAIR_OUTPUT


def build_pdfs() -> tuple[Path, Path]:
    return build_vehicle_pdf(), build_repair_pdf()


if __name__ == "__main__":
    for output in build_pdfs():
        print(output)
