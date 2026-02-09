from __future__ import annotations

import re
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from shared.curves import curve_model, load_curves


OUTPUT_DIR = Path("curves/images")

GROUP_COL = "group_id"
KM_COL = "km_anchor"
PRICE_COL = "price_median"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", value).strip("_")
    return slug


def main() -> None:
    df = load_curves()
    required = {GROUP_COL, KM_COL, PRICE_COL}
    missing = required - set(df.columns)
    if missing:
        raise SystemExit(f"Missing required columns: {', '.join(sorted(missing))}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    df = df.dropna(subset=[GROUP_COL, KM_COL, PRICE_COL])

    for group_id, group_df in df.groupby(GROUP_COL):
        group_df = group_df.sort_values(KM_COL)
        if len(group_df) < 3:
            continue

        fig, ax = plt.subplots(figsize=(10, 4))
        if curve_model() == "v2" and "anchor_year" in group_df.columns:
            for anchor_year, year_df in group_df.groupby("anchor_year"):
                year_df = year_df.sort_values(KM_COL)
                if len(year_df) < 2:
                    continue
                x = year_df[KM_COL].astype(float).values
                y = year_df[PRICE_COL].astype(float).values
                ax.plot(x, y, linewidth=2, label=str(anchor_year))
                ax.scatter(x, y, s=25)
            ax.legend(loc="best", frameon=False)
        else:
            x = group_df[KM_COL].astype(float).values
            y = group_df[PRICE_COL].astype(float).values
            ax.plot(x, y, linewidth=2)
            ax.scatter(x, y, s=30)

        ax.set_xlabel("Kilometres")
        ax.set_ylabel("Resale price ($)")
        ax.set_title(str(group_id))
        ax.grid(alpha=0.2)

        slug = _slugify(str(group_id))
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
