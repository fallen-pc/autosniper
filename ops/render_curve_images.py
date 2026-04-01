from __future__ import annotations

import re
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

if __package__ in (None, ""):
    import sys

    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from shared.canonical_tagging import tag_dataframe
    from shared.comps_engine import parse_currency, parse_numeric
    from shared.curves import load_curves
else:  # pragma: no cover
    from shared.canonical_tagging import tag_dataframe
    from shared.comps_engine import parse_currency, parse_numeric
    from shared.curves import load_curves


OUTPUT_DIR = Path("curves/images")
AUTOTRADER_TAGGED = Path("autotrader_isolated/output/first_page_results_tagged.csv")
AUTOTRADER_RAW = Path("autotrader_isolated/output/first_page_results.csv")

GROUP_COL = "canonical_tag"
KM_COL = "km_bucket"
PRICE_COL = "price_mid"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", value).strip("_")
    return slug


def _load_autotrader_points() -> pd.DataFrame:
    source_path: Path | None = None
    if AUTOTRADER_TAGGED.exists():
        source_path = AUTOTRADER_TAGGED
    elif AUTOTRADER_RAW.exists():
        source_path = AUTOTRADER_RAW
    if source_path is None:
        return pd.DataFrame(columns=["canonical_tag", "odometer_value", "price_value"])

    df = pd.read_csv(source_path)
    if df.empty:
        return pd.DataFrame(columns=["canonical_tag", "odometer_value", "price_value"])

    if "canonical_tag" not in df.columns or (df.get("canonical_tag", pd.Series(dtype=str)).fillna("").eq("").all()):
        df = tag_dataframe(
            df,
            source="render_curve_images",
            require_price=False,
            filter_unclassified=False,
            append_log=False,
        )

    df["canonical_tag"] = df.get("canonical_tag", "").fillna("").astype(str).str.strip()
    if "odometer_value" not in df.columns:
        df["odometer_value"] = df.get("odometer", pd.Series(dtype=object)).apply(parse_numeric)
    if "price_value" not in df.columns:
        df["price_value"] = df.get("price", pd.Series(dtype=object)).apply(parse_currency)

    points = df[["canonical_tag", "odometer_value", "price_value"]].copy()
    points = points[
        points["canonical_tag"].ne("")
        & points["canonical_tag"].ne("UNCLASSIFIED")
        & points["odometer_value"].notna()
        & points["price_value"].notna()
    ]
    points = points[
        (points["odometer_value"].astype(float) > 0)
        & (points["price_value"].astype(float) > 0)
    ]
    return points.reset_index(drop=True)


def main() -> None:
    df = load_curves()
    required = {GROUP_COL, KM_COL, PRICE_COL}
    missing = required - set(df.columns)
    if missing:
        raise SystemExit(f"Missing required columns: {', '.join(sorted(missing))}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    df = df.dropna(subset=[GROUP_COL, KM_COL, PRICE_COL])
    autotrader_points = _load_autotrader_points()

    for canonical_tag, tag_df in df.groupby(GROUP_COL):
        tag_df = tag_df.sort_values(KM_COL)
        if len(tag_df) < 3:
            continue

        fig, ax = plt.subplots(figsize=(10, 4))
        for anchor_year, year_df in tag_df.groupby("anchor_year"):
            year_df = year_df.sort_values(KM_COL)
            if len(year_df) < 2:
                continue
            x = year_df[KM_COL].astype(float).values
            y = year_df[PRICE_COL].astype(float).values
            ax.plot(x, y, linewidth=2, label=str(anchor_year))
            ax.scatter(x, y, s=25)
        tag_auto = autotrader_points[autotrader_points["canonical_tag"] == str(canonical_tag)]
        if not tag_auto.empty:
            ax.scatter(
                tag_auto["odometer_value"].astype(float).values,
                tag_auto["price_value"].astype(float).values,
                color="#ff7f0e",
                s=20,
                alpha=0.55,
                label="Autotrader",
            )
        ax.legend(loc="best", frameon=False)

        ax.set_xlabel("Kilometres")
        ax.set_ylabel("Resale price ($)")
        ax.set_title(str(canonical_tag))
        ax.grid(alpha=0.2)

        slug = _slugify(str(canonical_tag))
        if not slug:
            plt.close(fig)
            continue
        out_path = OUTPUT_DIR / f"{slug}.png"
        fig.tight_layout()
        fig.savefig(out_path, dpi=120)
        plt.close(fig)
        print(f"Rendered curve image -> {out_path}")


if __name__ == "__main__":
    main()
