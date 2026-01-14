import re
from collections import defaultdict

import pandas as pd
import streamlit as st

from shared.data_loader import dataset_path, ensure_datasets_available
from shared.styling import clean_html, display_banner, inject_global_styles, page_intro, render_logo_centered

st.set_page_config(page_title="Vehicle Repairs Library", layout="wide")
inject_global_styles()

display_banner()
page_intro(
    "VEHICLE REPAIRS",
    "Catalog repeated reconditioning items directly from the scraped inspection notes, then add ballpark pricing for each fix.",
)

missing = ensure_datasets_available(["vehicle_static_details.csv"])
if missing:
    st.error(
        "Required dataset `vehicle_static_details.csv` is missing. "
        "Configure `AUTOSNIPER_DATA_URL` or upload the CSV to `CSV_data/`."
    )
    st.stop()

VEHICLE_FILE = dataset_path("vehicle_static_details.csv")
ESTIMATES_FILE = dataset_path("repair_estimates.csv")

CATEGORY_RULES: list[tuple[str, list[str]]] = [
    (
        "Exterior / Body",
        [
            "scratch",
            "dent",
            "panel",
            "bumper",
            "windscreen",
            "window",
            "rust",
            "paint",
            "door",
            "quarter",
            "bonnet",
            "boot",
            "tailgate",
            "mirror",
            "headlight",
            "taillight",
            "grille",
            "wheel arch",
        ],
    ),
    (
        "Interior / Trim",
        [
            "seat",
            "trim",
            "interior",
            "carpet",
            "dashboard",
            "console",
            "headlining",
            "door card",
            "stain",
            "tear",
            "upholstery",
            "handle",
            "switch",
        ],
    ),
    (
        "Mechanical / Engine",
        [
            "engine",
            "gearbox",
            "transmission",
            "clutch",
            "brake",
            "rotor",
            "battery",
            "suspension",
            "shock",
            "strut",
            "leak",
            "oil",
            "coolant",
            "radiator",
            "timing belt",
            "smoke",
            "misfire",
        ],
    ),
]
DEFAULT_CATEGORY = "Other / Misc"
DEFAULT_SUBCATEGORY = "General"

EXTERIOR_SUBCATEGORIES: list[tuple[str, list[str]]] = [
    (
        "Dent / Panel Damage",
        [
            "dent",
            "panel",
            "crease",
            "quarter",
            "door",
            "tailgate",
            "bonnet",
            "boot",
            "guard",
            "roof",
        ],
    ),
    (
        "Paint / Clearcoat",
        [
            "paint",
            "peel",
            "peeling",
            "bubble",
            "clear coat",
            "fade",
            "oxidation",
            "respray",
            "stone chip",
            "scratch",
        ],
    ),
    (
        "Glass / Windscreen",
        [
            "windscreen",
            "windscreen chip",
            "windscreen crack",
            "window",
            "glass",
            "mirror",
        ],
    ),
    (
        "Bumper / Bars",
        [
            "bumper",
            "bar",
            "skirt",
            "spoiler",
            "splitter",
        ],
    ),
    (
        "Lighting / Trim",
        [
            "headlight",
            "tail light",
            "taillight",
            "indicator",
            "grille",
            "badge",
            "trim",
            "moulding",
        ],
    ),
]
EXTERIOR_SUBCATEGORY_DEFAULT = "Body - Other"


@st.cache_data(ttl=300)
def load_vehicle_data() -> pd.DataFrame:
    return pd.read_csv(VEHICLE_FILE)


@st.cache_data(ttl=60)
def load_estimates() -> pd.DataFrame:
    if ESTIMATES_FILE.exists():
        try:
            return pd.read_csv(ESTIMATES_FILE)
        except Exception:
            return pd.DataFrame(columns=["repair_key", "repair_item", "price_estimate"])
    return pd.DataFrame(columns=["repair_key", "repair_item", "price_estimate"])


def normalize_text(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def extract_repairs(entry: object) -> list[tuple[str, str]]:
    if entry is None or (isinstance(entry, float) and pd.isna(entry)):
        return []
    text = str(entry).strip()
    if not text or text.lower() in {"n/a", "na", "none"}:
        return []
    parts = re.split(r"[•\-\n\r;]+", text)
    repairs: list[tuple[str, str]] = []
    for part in parts:
        cleaned = part.strip().strip(".")
        if not cleaned:
            continue
        normalized = normalize_text(cleaned)
        if not normalized:
            continue
        repairs.append((normalized, cleaned))
    return repairs


def assemble_vehicle_title(row: pd.Series) -> str:
    parts = [
        str(row.get("year", "")).split(".")[0],
        str(row.get("make", "")).strip(),
        str(row.get("model", "")).strip(),
        str(row.get("variant", "")).strip(),
    ]
    title = " ".join(filter(None, parts))
    return title or "Unknown vehicle"


def _determine_exterior_subcategory(normalized_text: str) -> str:
    for label, keywords in EXTERIOR_SUBCATEGORIES:
        if any(keyword in normalized_text for keyword in keywords):
            return label
    return EXTERIOR_SUBCATEGORY_DEFAULT


def categorize_repair(normalized_text: str) -> tuple[str, str]:
    for category, keywords in CATEGORY_RULES:
        if any(keyword in normalized_text for keyword in keywords):
            subcategory = (
                _determine_exterior_subcategory(normalized_text)
                if category == "Exterior / Body"
                else DEFAULT_SUBCATEGORY
            )
            return category, subcategory
    return DEFAULT_CATEGORY, DEFAULT_SUBCATEGORY


df = load_vehicle_data()
condition_column = df.get("general_condition")
if condition_column is None or condition_column.empty:
    st.info("No general condition data available to derive repairs.")
    st.stop()

repairs_map: dict[str, dict[str, object]] = {}
examples: dict[str, list[str]] = defaultdict(list)

for _, row in df.iterrows():
    vehicle_title = assemble_vehicle_title(row)
    vehicle_url = str(row.get("url", "")).strip()
    entry_label = f"{vehicle_title}"
    if vehicle_url:
        entry_label = f"{vehicle_title} ({vehicle_url})"
    for key, label in extract_repairs(row.get("general_condition")):
        category, subcategory = categorize_repair(key)
        info = repairs_map.setdefault(
            key,
            {
                "repair_key": key,
                "repair_item": label,
                "occurrences": 0,
                "category": category,
                "sub_category": subcategory,
            },
        )
        info["occurrences"] += 1
        sample_list = examples[key]
        if len(sample_list) < 3:
            sample_list.append(entry_label)

if not repairs_map:
    st.info("No repair notes detected in the current dataset.")
    st.stop()

repairs_df = pd.DataFrame(repairs_map.values())
repairs_df["examples"] = repairs_df["repair_key"].apply(lambda key: examples.get(key, []))
repairs_df["example_preview"] = repairs_df["examples"].apply(lambda vals: " • ".join(vals))
repairs_df.sort_values(by=["category", "sub_category", "occurrences"], ascending=[True, True, False], inplace=True)

estimates_df = load_estimates()
if not estimates_df.empty:
    repairs_df = repairs_df.merge(
        estimates_df,
        on="repair_key",
        how="left",
        suffixes=("", "_saved"),
    )
    repairs_df["repair_item"] = repairs_df["repair_item"].fillna(repairs_df["repair_item_saved"])
    repairs_df["price_estimate"] = repairs_df["price_estimate"].fillna(repairs_df.get("price_estimate_saved"))
    repairs_df.drop(columns=[col for col in repairs_df.columns if col.endswith("_saved")], inplace=True)
else:
    repairs_df["price_estimate"] = pd.NA

st.sidebar.markdown("### Repair Navigator")
occ_max = int(repairs_df["occurrences"].max())
if occ_max <= 1:
    min_count = 1
    st.sidebar.caption("Showing all items (each repair only appears once).")
else:
    min_count = st.sidebar.slider(
        "Minimum occurrences to display",
        min_value=1,
        max_value=occ_max,
        value=1,
    )
search_text = st.sidebar.text_input("Search within selection")

base_df = repairs_df[repairs_df["occurrences"] >= min_count].copy()
if base_df.empty:
    st.info("No repairs match the current occurrence threshold. Lower the slider to see results.")
    st.stop()

if "repair_path" not in st.session_state:
    st.session_state.repair_path = {
        "category": sorted(base_df["category"].unique())[0],
        "sub_category": None,
        "repair_item": "All repairs",
    }

category_options = sorted(base_df["category"].unique())
default_category = st.session_state.repair_path.get("category", category_options[0])
if default_category not in category_options:
    default_category = category_options[0]

with st.expander("1. Choose Category", expanded=True):
    category_choice = st.radio(
        "Category",
        options=category_options,
        index=category_options.index(default_category),
        horizontal=True,
    )

subcat_options = sorted(base_df[base_df["category"] == category_choice]["sub_category"].unique())
default_subcat = st.session_state.repair_path.get("sub_category") or subcat_options[0]
if default_subcat not in subcat_options:
    default_subcat = subcat_options[0]

with st.expander("2. Choose Sub-category", expanded=True):
    subcat_choice = st.radio(
        "Sub-category",
        options=subcat_options,
        index=subcat_options.index(default_subcat),
        horizontal=True,
    )

scoped_df = base_df[
    (base_df["category"] == category_choice) & (base_df["sub_category"] == subcat_choice)
].copy()

repair_options = ["All repairs"] + sorted(scoped_df["repair_item"].unique())
default_repair = st.session_state.repair_path.get("repair_item", "All repairs")
if default_repair not in repair_options:
    default_repair = "All repairs"

with st.expander("3. Choose Repair Detail", expanded=True):
    repair_choice = st.radio(
        "Repair detail",
        options=repair_options,
        index=repair_options.index(default_repair),
        horizontal=True,
    )

if repair_choice != "All repairs":
    scoped_df = scoped_df[scoped_df["repair_item"] == repair_choice].copy()

if search_text:
    needle = search_text.strip().lower()
    scoped_df = scoped_df[
        scoped_df["repair_item"].str.lower().str.contains(needle)
        | scoped_df["repair_key"].str.contains(needle)
    ].copy()

st.session_state.repair_path = {
    "category": category_choice,
    "sub_category": subcat_choice,
    "repair_item": repair_choice,
}

if scoped_df.empty:
    st.info("No repairs found for the selected path. Try relaxing the filters.")
    st.stop()

path_html = clean_html(
    f"""
    <div class="autosniper-section">
        <div class="section-title">Repair Catalogue</div>
        <div class="section-subtitle">
            Path: <strong>{category_choice}</strong> → <strong>{subcat_choice}</strong>
            ({len(scoped_df):,} item(s) · occurrences ≥ {min_count})
        </div>
    </div>
    """
)
st.markdown(path_html, unsafe_allow_html=True)

top_examples = scoped_df.sort_values(by="occurrences", ascending=False).head(3)
cols = st.columns(len(top_examples))
for idx, (_, row) in enumerate(top_examples.iterrows()):
    cols[idx].metric(
        label=row["repair_item"],
        value=f"{int(row['occurrences'])} mentions",
        delta=(
            f"Est. ${row['price_estimate']:.0f}"
            if pd.notna(row["price_estimate"])
            else "Set estimate"
        ),
    )

column_config = {
    "repair_item": st.column_config.TextColumn("Repair Item", help="Description extracted from inspection notes."),
    "occurrences": st.column_config.NumberColumn("Occurrences", format="%d"),
    "category": st.column_config.TextColumn("Category"),
    "sub_category": st.column_config.TextColumn("Sub-category"),
    "example_preview": st.column_config.TextColumn("Sample Vehicles", help="First few vehicles mentioning this repair."),
    "price_estimate": st.column_config.NumberColumn("Price Estimate ($)", min_value=0.0, step=25.0),
}

editor_df = scoped_df[
    ["repair_key", "repair_item", "category", "sub_category", "occurrences", "example_preview", "price_estimate"]
]
edited_df = st.data_editor(
    editor_df,
    hide_index=True,
    column_config=column_config,
    disabled=["repair_key", "repair_item", "category", "sub_category", "occurrences", "example_preview"],
    width="stretch",
    num_rows="dynamic",
    key="repairs_editor",
)

st.caption("Add or adjust price estimates for the current selection, then save your changes.")


def save_estimates(dataframe: pd.DataFrame) -> None:
    cleaned = dataframe[["repair_key", "repair_item", "price_estimate"]].copy()
    cleaned = cleaned.dropna(subset=["price_estimate"])
    if cleaned.empty:
        if ESTIMATES_FILE.exists():
            ESTIMATES_FILE.unlink()
        return
    cleaned["price_estimate"] = cleaned["price_estimate"].astype(float)
    cleaned.to_csv(ESTIMATES_FILE, index=False)


col1, col2 = st.columns([1, 3])
with col1:
    if st.button("Save repair estimates", type="primary"):
        save_estimates(edited_df)
        load_estimates.clear()
        st.success("Repair estimates saved.")
with col2:
    st.caption(f"Saved to `{ESTIMATES_FILE.name}` in CSV_data.")
