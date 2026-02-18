from __future__ import annotations

import re
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from shared.curves import load_curves


OUTPUT_DIR = Path("curves/images")

GROUP_COL = "canonical_tag"
KM_COL = "km_bucket"
PRICE_COL = "price_mid"


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
