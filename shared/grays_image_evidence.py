from __future__ import annotations

import hashlib
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup, Tag

from shared.csv_utils import CSV_READ_ERRORS, read_csv_or_empty


DEFAULT_INPUTS = [
    Path("CSV_data/scrapers/active_vehicle_details.csv"),
    Path("CSV_data/scrapers/vehicle_static_details.csv"),
]
DEFAULT_MANIFEST_OUTPUT = Path("output/grays_images/grays_image_manifest.csv")
DEFAULT_LINKS_OUTPUT = Path("CSV_data/reports/grays_repair_image_links.csv")
DEFAULT_IMAGE_CACHE_DIR = Path("output/grays_images/cache")
DEFAULT_REPAIR_FRAGMENTS_PATH = Path("CSV_data/reports/grays_condition_repair_fragments.csv")

IMAGE_MANIFEST_COLUMNS = [
    "source",
    "listing_id",
    "lot_id",
    "listing_url",
    "image_url",
    "position",
    "alt_text",
    "caption",
    "image_sha256",
    "content_type",
    "bytes",
    "local_path",
    "download_status",
    "error",
]

REPAIR_IMAGE_LINK_COLUMNS = [
    "listing_url",
    "listing_id",
    "lot_id",
    "image_url",
    "local_path",
    "position",
    "repair_key",
    "repair_item",
    "canonical_defects",
    "category",
    "status",
    "match_method",
    "confidence",
    "notes",
]

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".avif"}
IMAGE_URL_HINT_RE = re.compile(r"\.(?:jpe?g|png|webp|avif)(?:[?#]|$)", re.IGNORECASE)
LOT_RE = re.compile(r"/lot/([^/?#]+)", re.IGNORECASE)
SRCSET_SPLIT_RE = re.compile(r"\s*,\s*")
WORD_RE = re.compile(r"[a-z0-9]{3,}")


@dataclass(frozen=True)
class ImageCandidate:
    image_url: str
    alt_text: str = ""
    caption: str = ""


def safe_text(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    return text


def lot_id_from_url(url: object) -> str:
    text = safe_text(url)
    match = LOT_RE.search(text)
    return match.group(1) if match else ""


def listing_id_from_url(url: object) -> str:
    lot_id = lot_id_from_url(url)
    if lot_id:
        return lot_id
    parsed = urlparse(safe_text(url))
    return hashlib.sha1(parsed.path.encode("utf-8")).hexdigest()[:12] if parsed.path else ""


def is_grays_listing_url(url: object) -> bool:
    text = safe_text(url).lower()
    return text.startswith("https://www.grays.com/lot/") or text.startswith("http://www.grays.com/lot/")


def iter_listing_urls(paths: Iterable[Path], *, limit: int | None = None) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for path in paths:
        df = read_csv_or_empty(path, dtype=str, keep_default_na=False)
        if df.empty or "url" not in df.columns:
            continue
        for raw_url in df["url"].tolist():
            url = safe_text(raw_url)
            key = url.lower()
            if not is_grays_listing_url(url) or key in seen:
                continue
            seen.add(key)
            urls.append(url)
            if limit is not None and len(urls) >= limit:
                return urls
    return urls


def _normalize_image_url(base_url: str, image_url: object) -> str:
    text = safe_text(image_url)
    if not text or text.startswith("data:"):
        return ""
    if text.startswith("//"):
        text = f"https:{text}"
    return urljoin(base_url, text)


def _srcset_urls(value: object) -> list[str]:
    text = safe_text(value)
    if not text:
        return []
    urls = []
    for part in SRCSET_SPLIT_RE.split(text):
        first = part.strip().split(" ", 1)[0]
        if first:
            urls.append(first)
    return urls


def _looks_like_vehicle_image(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    if Path(path).suffix in IMAGE_EXTENSIONS:
        return True
    if IMAGE_URL_HINT_RE.search(url):
        return True
    return any(token in path for token in ("/image", "/images", "/photo", "/photos", "/asset"))


def _nearest_caption(tag: Tag) -> str:
    figure = tag.find_parent("figure")
    if figure:
        caption = figure.find("figcaption")
        if caption:
            return caption.get_text(" ", strip=True)
    parent = tag.parent
    if isinstance(parent, Tag):
        labelled = parent.get("aria-label") or parent.get("title")
        if labelled:
            return safe_text(labelled)
    return ""


def extract_image_candidates(html: str, listing_url: str) -> list[ImageCandidate]:
    soup = BeautifulSoup(html or "", "html.parser")
    candidates: list[ImageCandidate] = []
    seen: set[str] = set()

    def add(raw_url: object, *, alt_text: object = "", caption: object = "") -> None:
        url = _normalize_image_url(listing_url, raw_url)
        if not url or url in seen or not _looks_like_vehicle_image(url):
            return
        seen.add(url)
        candidates.append(ImageCandidate(url, safe_text(alt_text), safe_text(caption)))

    for tag in soup.find_all("img"):
        if not isinstance(tag, Tag):
            continue
        alt_text = tag.get("alt") or tag.get("title") or tag.get("aria-label") or ""
        caption = _nearest_caption(tag)
        for attr in ("src", "data-src", "data-original", "data-lazy-src"):
            add(tag.get(attr), alt_text=alt_text, caption=caption)
        for srcset_attr in ("srcset", "data-srcset"):
            for raw_url in _srcset_urls(tag.get(srcset_attr)):
                add(raw_url, alt_text=alt_text, caption=caption)

    for meta in soup.find_all("meta"):
        if not isinstance(meta, Tag):
            continue
        prop = safe_text(meta.get("property") or meta.get("name")).lower()
        if prop in {"og:image", "twitter:image", "twitter:image:src"}:
            add(meta.get("content"), caption=prop)

    return candidates


def build_manifest_rows(listing_url: str, candidates: Iterable[ImageCandidate]) -> list[dict[str, object]]:
    lot_id = lot_id_from_url(listing_url)
    listing_id = listing_id_from_url(listing_url)
    rows = []
    for position, candidate in enumerate(candidates, start=1):
        rows.append(
            {
                "source": "grays",
                "listing_id": listing_id,
                "lot_id": lot_id,
                "listing_url": listing_url,
                "image_url": candidate.image_url,
                "position": position,
                "alt_text": candidate.alt_text,
                "caption": candidate.caption,
                "image_sha256": "",
                "content_type": "",
                "bytes": "",
                "local_path": "",
                "download_status": "discovered",
                "error": "",
            }
        )
    return rows


def merge_manifest(existing: pd.DataFrame, incoming_rows: list[dict[str, object]]) -> pd.DataFrame:
    incoming = pd.DataFrame(incoming_rows, columns=IMAGE_MANIFEST_COLUMNS)
    if existing.empty:
        combined = incoming
    else:
        current = existing.copy()
        for column in IMAGE_MANIFEST_COLUMNS:
            if column not in current.columns:
                current[column] = ""
        combined = pd.concat([current[IMAGE_MANIFEST_COLUMNS], incoming], ignore_index=True)
    if combined.empty:
        return pd.DataFrame(columns=IMAGE_MANIFEST_COLUMNS)
    combined = combined.fillna("")
    combined["_key"] = (
        combined["listing_url"].astype(str).str.strip().str.lower()
        + "|"
        + combined["image_url"].astype(str).str.strip()
    )
    rows: list[dict[str, object]] = []
    cache_columns = {"image_sha256", "content_type", "bytes", "local_path"}
    for _, group in combined.groupby("_key", sort=False):
        latest = group.iloc[-1].to_dict()
        for column in cache_columns:
            nonblank = [safe_text(value) for value in group[column].tolist() if safe_text(value)]
            if nonblank:
                latest[column] = nonblank[-1]
        if safe_text(latest.get("local_path")):
            latest["download_status"] = "downloaded"
            latest["error"] = ""
        rows.append({column: latest.get(column, "") for column in IMAGE_MANIFEST_COLUMNS})
    return pd.DataFrame(rows, columns=IMAGE_MANIFEST_COLUMNS).reset_index(drop=True)


def download_manifest_images(
    manifest: pd.DataFrame,
    *,
    cache_dir: Path = DEFAULT_IMAGE_CACHE_DIR,
    session: requests.Session | None = None,
    timeout: float = 25.0,
) -> pd.DataFrame:
    if manifest.empty:
        return manifest.copy()
    out = manifest.copy().fillna("")
    cache_dir.mkdir(parents=True, exist_ok=True)
    own_session = session is None
    http = session or requests.Session()
    http.headers.setdefault(
        "User-Agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    )
    try:
        for idx, row in out.iterrows():
            if safe_text(row.get("local_path")) and Path(safe_text(row.get("local_path"))).exists():
                continue
            image_url = safe_text(row.get("image_url"))
            if not image_url:
                continue
            try:
                response = http.get(image_url, timeout=timeout)
                response.raise_for_status()
                content = response.content
                digest = hashlib.sha256(content).hexdigest()
                content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip()
                extension = mimetypes.guess_extension(content_type) or Path(urlparse(image_url).path).suffix or ".img"
                extension = ".jpg" if extension == ".jpe" else extension
                lot_id = safe_text(row.get("lot_id")) or safe_text(row.get("listing_id")) or "listing"
                position = safe_text(row.get("position")) or str(idx + 1)
                local_path = cache_dir / lot_id / f"{int(position):03d}-{digest[:16]}{extension}"
                local_path.parent.mkdir(parents=True, exist_ok=True)
                if not local_path.exists():
                    local_path.write_bytes(content)
                out.at[idx, "image_sha256"] = digest
                out.at[idx, "content_type"] = content_type
                out.at[idx, "bytes"] = len(content)
                out.at[idx, "local_path"] = str(local_path)
                out.at[idx, "download_status"] = "downloaded"
                out.at[idx, "error"] = ""
            except requests.RequestException as exc:
                out.at[idx, "download_status"] = "failed"
                out.at[idx, "error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if own_session:
            http.close()
    return out[IMAGE_MANIFEST_COLUMNS]


def _token_set(*values: object) -> set[str]:
    text = " ".join(safe_text(value).lower() for value in values)
    return {token for token in WORD_RE.findall(text) if token not in {"with", "that", "this", "from", "front", "rear"}}


def _image_repair_match(image_row: pd.Series, repair_row: pd.Series) -> tuple[str, str, str]:
    visual_tokens = _token_set(image_row.get("alt_text"), image_row.get("caption"), image_row.get("image_url"))
    repair_tokens = _token_set(
        repair_row.get("repair_item"),
        repair_row.get("repair_key"),
        repair_row.get("canonical_defects"),
        repair_row.get("category"),
    )
    overlap = visual_tokens & repair_tokens
    if overlap:
        return "image_text_token_overlap", "medium", "Image text overlaps repair terms: " + ", ".join(sorted(overlap)[:6])
    return "listing_url_join", "low", "Image belongs to the same Grays listing; specific damaged area not confirmed."


def build_repair_image_links(
    manifest: pd.DataFrame,
    repair_fragments: pd.DataFrame,
) -> pd.DataFrame:
    if manifest.empty or repair_fragments.empty or "url" not in repair_fragments.columns:
        return pd.DataFrame(columns=REPAIR_IMAGE_LINK_COLUMNS)
    image_df = manifest.copy().astype(object).where(pd.notna(manifest), "")
    repairs = repair_fragments.copy().astype(object).where(pd.notna(repair_fragments), "")
    image_df["_url_norm"] = image_df["listing_url"].astype(str).str.strip().str.lower()
    repairs["_url_norm"] = repairs["url"].astype(str).str.strip().str.lower()
    joined = image_df.merge(repairs, on="_url_norm", how="inner", suffixes=("_image", "_repair"))
    rows: list[dict[str, object]] = []
    for _, row in joined.iterrows():
        match_method, confidence, notes = _image_repair_match(row, row)
        rows.append(
            {
                "listing_url": safe_text(row.get("listing_url")),
                "listing_id": safe_text(row.get("listing_id")),
                "lot_id": safe_text(row.get("lot_id")),
                "image_url": safe_text(row.get("image_url")),
                "local_path": safe_text(row.get("local_path")),
                "position": safe_text(row.get("position")),
                "repair_key": safe_text(row.get("repair_key")),
                "repair_item": safe_text(row.get("repair_item")),
                "canonical_defects": safe_text(row.get("canonical_defects")),
                "category": safe_text(row.get("category")),
                "status": safe_text(row.get("status")),
                "match_method": match_method,
                "confidence": confidence,
                "notes": notes,
            }
        )
    out = pd.DataFrame(rows, columns=REPAIR_IMAGE_LINK_COLUMNS)
    if out.empty:
        return out
    return out.drop_duplicates(
        subset=["listing_url", "image_url", "repair_key", "repair_item"],
        keep="last",
    ).reset_index(drop=True)


def read_manifest(path: Path = DEFAULT_MANIFEST_OUTPUT) -> pd.DataFrame:
    try:
        return read_csv_or_empty(path, dtype=str, keep_default_na=False)
    except CSV_READ_ERRORS:
        return pd.DataFrame(columns=IMAGE_MANIFEST_COLUMNS)
