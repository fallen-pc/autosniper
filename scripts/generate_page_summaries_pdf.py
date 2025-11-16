from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class PageSummary:
    """Data needed to summarise a Streamlit page."""

    title: str
    purpose: str
    capabilities: tuple[str, ...]
    data_flows: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)


WRAP_WIDTH = 92
PAGE_HEIGHT_PT = 792  # Letter page height in points
MARGIN_PT = 72
TITLE_FONT_SIZE = 18
BODY_FONT_SIZE = 12
TITLE_LEADING = 20
BODY_LEADING = 15


PAGE_SUMMARIES: tuple[PageSummary, ...] = (
    PageSummary(
        title="1. Link Extractor",
        purpose=(
            "Collect a clean list of every active Grays auction URL so downstream scrapers and dashboards"
            " always start from a consistent queue of listings."
        ),
        capabilities=(
            "Runs `scripts/extract_links.py` when the **Run link scraper** button is pressed and surfaces"
            " immediate success / failure feedback in the UI.",
            "Counts the rows in `CSV_data/all_vehicle_links.csv` and previews the first 20 links so you"
            " know what was captured in the latest crawl.",
        ),
        data_flows=(
            "Input: none — the scraper hits Grays directly.",
            "Output: `CSV_data/all_vehicle_links.csv` (listing URL, title, metadata).",
        ),
        notes=(
            "Kick this page off whenever you want to refresh the entire discovery pipeline before"
            " running deeper scrapes.",
        ),
    ),
    PageSummary(
        title="2. Vehicle Detail Extractor",
        purpose=(
            "Expand each tracked link into a fully structured record that captures specs, condition"
            " notes, pricing, and other static context for the Active Listings dashboard."
        ),
        capabilities=(
            "Guards against missing link data — if `all_vehicle_links.csv` does not exist the page blocks"
            " you from running the detail scraper and surfaces an error state.",
            "Runs `scripts/extract_vehicle_details.py`, then previews up to 50 rows from"
            " `vehicle_static_details.csv` along with a total count so you can sanity-check the pull.",
        ),
        data_flows=(
            "Input: `CSV_data/all_vehicle_links.csv` (required).",
            "Output: `CSV_data/vehicle_static_details.csv` (master spec sheet for each listing).",
        ),
        notes=(
            "Use this immediately after refreshing the link list so the remaining tools have up-to-date"
            " vehicle snapshots.",
        ),
    ),
    PageSummary(
        title="3. Active Listings Dashboard",
        purpose=(
            "Serve as the mission control for live auctions: filter noisy stock, refresh bid data, and"
            " optionally trigger GPT-powered profit checks per vehicle."
        ),
        capabilities=(
            "Loads `vehicle_static_details.csv`, enforces that only `status == 'active'` records remain,"
            " and displays listing cards grouped by time-to-close buckets (""<24h", "1-2d", "2-3d", "3+d"").",
            "Sidebar filters hide engine defect notes, unregistered vehicles, and/or anything outside"
            " Victoria so buyers can focus on viable stock.",
            "Provides **Refresh Active Listings** and **Refresh Visible Listings** actions that call"
            " `scripts.update_bids.update_bids` (optionally limited to the filtered URLs).",
            "Each card exposes a ""Run AI Analysis"" button. The handler sends the row through the OpenAI"
            " chat API, parses a JSON resale verdict, and persists the result in"
            " `CSV_data/ai_verdicts.csv` for future sessions.",
        ),
        data_flows=(
            "Inputs: `vehicle_static_details.csv` plus optional `ai_verdicts.csv` for overlaying prior"
            " AI recommendations.",
            "Outputs: updated `vehicle_static_details.csv` (bid/time refreshes) and appended"
            " `ai_verdicts.csv` rows when new analyses run.",
        ),
        notes=(
            "Skipped URLs from bid refreshes are cached in-session so you can retry only the failures.",
        ),
    ),
    PageSummary(
        title="4. Master Database Overview",
        purpose=(
            "Provide a quick audit of every lifecycle stage — active listings, sold stock, and referred"
            " vehicles — without jumping between CSVs."
        ),
        capabilities=(
            "Verifies the presence of `vehicle_static_details.csv`, `sold_cars.csv`, and"
            " `referred_cars.csv` before rendering so you catch missing exports early.",
            "Exposes an **Update Master Database** button that runs `scripts/update_master.py` and"
            " clears Streamlit caches so fresh data is immediately visible.",
            "Uses a reusable renderer to show record counts plus up to 200-row previews for the Active,"
            " Sold, and Referred datasets (with the most relevant columns per table).",
        ),
        data_flows=(
            "Inputs: the three CSV snapshots mentioned above.",
            "Output: refreshed CSVs when `update_master.py` is executed.",
        ),
        notes=(
            "Any missing columns are explicitly flagged so schema drift is easy to spot.",
        ),
    ),
    PageSummary(
        title="5. AI Pricing Analysis",
        purpose=(
            "Blend rule-based pricing heuristics, historical sale comps, manual Carsales research, and"
            " GPT valuations to prioritise listings finishing soon."
        ),
        capabilities=(
            "Requires a rich data stack (`vehicle_static_details.csv`, `active_vehicle_details.csv`,"
            " `ai_verdicts.csv`, `ai_listing_valuations.csv`, and `sold_cars.csv`) so comparisons always"
            " combine the latest auction context with historical baselines.",
            "Lets you focus on a time window (24/48/72h) plus reuse the Active Listings filters to hide"
            " engine issues, unregistered stock, or non-VIC locations.",
            "Calculates median discounts versus comparable sales, surfaces the most underpriced cars in"
            " one tab, and routes listings with no comps into a second review queue.",
            "Inside each listing panel you can refresh bid data, run or re-run the Carsales-oriented GPT"
            " valuation (`scripts.ai_listing_valuation.run_ai_listing_analysis`), and capture manual"
            " Carsales research (instant offer, sell range, comps table, recent sales).",
            "AI verdict widgets show Carsales estimate, recommended max bid, expected profit, and any"
            " qualitative confidence notes saved in the cache.",
        ),
        data_flows=(
            "Inputs: active auction snapshots, historical sold data, cached AI Carsales checks, and"
            " operator-entered Carsales estimates.",
            "Outputs: updated `ai_listing_valuations.csv` plus refreshed bid data when you trigger"
            " updates from the page.",
        ),
        notes=(
            "The page stores manual Carsales inputs per URL in `st.session_state` so partially entered"
            " values persist while you compare vehicles.",
        ),
    ),
    PageSummary(
        title="6. Missed Opportunities",
        purpose=(
            "Cross-check recent sale prices against the manual Carsales valuations to highlight deals"
            " that should have been bought."),
        capabilities=(
            "Loads cached Carsales tables and `sold_cars.csv`, filters to sold records, and computes the"
            " profit gap between the manual average price and the actual hammer price.",
            "Shows the top three gaps as callouts plus a full table with currency-formatted pricing and"
            " odometer stats so you can review the evidence.",
        ),
        data_flows=(
            "Inputs: `ai_listing_valuations.csv` (for manual Carsales data) and `sold_cars.csv`.",
            "Output: in-app leaderboard of positive profit deltas for post-mortems.",
        ),
        notes=(
            "Every calculation normalises the saved text values into numeric form, so even loosely"
            " structured Carsales notes can be compared objectively.",
        ),
    ),
    PageSummary(
        title="7. Outcome Accuracy Tracker",
        purpose=(
            "Measure how well AI predictions performed once vehicles settled, broken down by time,"
            " verdict tier, and individual misses."),
        capabilities=(
            "Requires `ai_listing_valuations.csv`, `sold_cars.csv`, and `ai_verdicts.csv`, then calls"
            " `scripts.outcome_tracking.compute_outcome_metrics()` to assemble joined datasets.",
            "Displays aggregate KPIs (scored listings, accuracy, MAE, MAPE, profit calibration) plus"
            " Altair charts for weekly hit rates and accuracy by verdict tier.",
            "Provides a detailed ""Worst Misses"" table and download buttons for the scored listings,"
            " weekly metrics, and verdict metrics CSVs so analysts can dig deeper offline.",
        ),
        data_flows=(
            "Inputs: joined AI verdicts, pricing analyses, and sold outcomes.",
            "Outputs: exported CSVs for accuracy tracking and on-screen diagnostics.",
        ),
        notes=(
            "Metrics update inside a spinner whenever the page loads to keep the accuracy dashboard"
            " consistent with the freshest data on disk.",
        ),
    ),
    PageSummary(
        title="99. Style Guide & Template",
        purpose=(
            "Act as a living design system so new Streamlit pages stay on brand without guesswork."),
        capabilities=(
            "Applies the shared global CSS tokens, displays the AutoSniper colour palette with token"
            " names, and demonstrates responsive grid layouts, cards, and button styles.",
            "Provides copy-ready HTML snippets (banner, palette, button rows) developers can reuse when"
            " building future tooling pages.",
        ),
        notes=(
            "Use this page as a reference when adding UI polish or troubleshooting layout spacing.",
        ),
    ),
)


def wrap_paragraph(text: str, width: int = WRAP_WIDTH) -> list[str]:
    wrapper = textwrap.TextWrapper(width=width)
    return wrapper.wrap(text)


def wrap_list(entries: Iterable[str], prefix: str) -> list[str]:
    lines: list[str] = []
    for entry in entries:
        wrapper = textwrap.TextWrapper(
            width=WRAP_WIDTH,
            initial_indent=prefix,
            subsequent_indent=" " * len(prefix),
        )
        lines.extend(wrapper.wrap(entry))
    return lines


def escape_pdf_text(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .replace("\r", "")
    )


def build_page_lines(summary: PageSummary) -> list[str]:
    lines: list[str] = []
    lines.append("Purpose")
    lines.extend(wrap_paragraph(summary.purpose))
    lines.append("")
    lines.append("Key capabilities")
    lines.extend(wrap_list(summary.capabilities, "• "))
    if summary.data_flows:
        lines.append("")
        lines.append("Data flow")
        lines.extend(wrap_list(summary.data_flows, "→ "))
    if summary.notes:
        lines.append("")
        lines.append("Notes")
        lines.extend(wrap_list(summary.notes, "– "))
    return lines


def page_stream(summary: PageSummary) -> str:
    lines = build_page_lines(summary)
    content: list[str] = [
        "BT",
        f"/F1 {TITLE_FONT_SIZE} Tf",
        f"{TITLE_LEADING} TL",
        f"1 0 0 1 {MARGIN_PT} {PAGE_HEIGHT_PT - MARGIN_PT} Tm",
        f"({escape_pdf_text(summary.title)}) Tj",
        f"/F1 {BODY_FONT_SIZE} Tf",
        f"{BODY_LEADING} TL",
    ]
    for line in lines:
        content.append("T*")
        if line:
            content.append(f"({escape_pdf_text(line)}) Tj")
    content.append("ET")
    return "\n".join(content)


def write_pdf(output_path: Path, summaries: Iterable[PageSummary]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    objects: list[str | None] = []

    def reserve_object() -> int:
        objects.append(None)
        return len(objects)

    def set_object(object_id: int, value: str) -> None:
        objects[object_id - 1] = value

    catalog_id = reserve_object()
    pages_id = reserve_object()
    font_id = reserve_object()
    set_object(font_id, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    page_ids: list[int] = []
    content_ids: list[int] = []
    for summary in summaries:
        content_id = reserve_object()
        page_id = reserve_object()
        content_ids.append(content_id)
        page_ids.append(page_id)
        stream = page_stream(summary)
        set_object(
            content_id,
            f"<< /Length {len(stream.encode('utf-8'))} >>\nstream\n{stream}\nendstream",
        )
        set_object(
            page_id,
            "<< /Type /Page /Parent {parent} 0 R /MediaBox [0 0 612 792] "
            "/Resources << /Font << /F1 {font} 0 R >> >> /Contents {content} 0 R >>".format(
                parent=pages_id,
                font=font_id,
                content=content_id,
            ),
        )

    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    set_object(pages_id, f"<< /Type /Pages /Count {len(page_ids)} /Kids [{kids}] >>")
    set_object(catalog_id, f"<< /Type /Catalog /Pages {pages_id} 0 R >>")

    if any(entry is None for entry in objects):
        raise RuntimeError("One or more PDF objects were not initialised.")

    with output_path.open("wb") as pdf_file:
        pdf_file.write(b"%PDF-1.4\n")
        offsets: list[int] = []
        for object_id, body in enumerate(objects, start=1):
            offsets.append(pdf_file.tell())
            pdf_file.write(f"{object_id} 0 obj\n".encode("utf-8"))
            pdf_file.write(body.encode("utf-8"))
            pdf_file.write(b"\nendobj\n")
        xref_position = pdf_file.tell()
        pdf_file.write(f"xref\n0 {len(objects) + 1}\n".encode("utf-8"))
        pdf_file.write(b"0000000000 65535 f \n")
        for offset in offsets:
            pdf_file.write(f"{offset:010d} 00000 n \n".encode("utf-8"))
        pdf_file.write(
            (
                "trailer\n"
                f"<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n"
                "startxref\n"
                f"{xref_position}\n"
                "%%EOF"
            ).encode("utf-8")
        )


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    output_pdf = repo_root / "artifacts" / "autosniper_page_overview.pdf"
    write_pdf(output_pdf, PAGE_SUMMARIES)
    print(f"Wrote {output_pdf.relative_to(repo_root)}")


if __name__ == "__main__":
    main()
