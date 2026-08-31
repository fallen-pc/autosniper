from __future__ import annotations

import pandas as pd

from shared.grays_image_evidence import (
    build_manifest_rows,
    build_repair_image_links,
    extract_image_candidates,
    iter_listing_urls,
    merge_manifest,
)


LISTING_URL = "https://www.grays.com/lot/0001-23501266/motor-vehicles-motor-cycles/example-car"


def test_extract_image_candidates_reads_img_srcset_and_social_meta() -> None:
    html = """
    <html>
      <head>
        <meta property="og:image" content="https://cdn.example.test/lot/main.jpg?width=1200">
      </head>
      <body>
        <figure>
          <img src="/assets/car-front.jpg" alt="Front bumper scratched">
          <figcaption>front bumper</figcaption>
        </figure>
        <img
          data-src="//cdn.example.test/photos/side.webp"
          srcset="//cdn.example.test/photos/side-small.webp 400w, //cdn.example.test/photos/side-large.webp 1200w"
          alt="Driver door dent">
        <img src="data:image/gif;base64,AAAA" alt="ignored">
      </body>
    </html>
    """

    candidates = extract_image_candidates(html, LISTING_URL)

    urls = [candidate.image_url for candidate in candidates]
    assert "https://www.grays.com/assets/car-front.jpg" in urls
    assert "https://cdn.example.test/photos/side.webp" in urls
    assert "https://cdn.example.test/photos/side-large.webp" in urls
    assert "https://cdn.example.test/lot/main.jpg?width=1200" in urls
    assert candidates[0].alt_text == "Front bumper scratched"
    assert candidates[0].caption == "front bumper"


def test_manifest_merge_dedupes_by_listing_and_image_url() -> None:
    rows = build_manifest_rows(
        LISTING_URL,
        extract_image_candidates("<img src='/photos/a.jpg' alt='a'><img src='/photos/a.jpg' alt='dupe'>", LISTING_URL),
    )

    merged = merge_manifest(pd.DataFrame(), rows + rows)

    assert len(merged) == 1
    assert merged.loc[0, "lot_id"] == "0001-23501266"
    assert merged.loc[0, "download_status"] == "discovered"


def test_manifest_merge_preserves_downloaded_cache_metadata() -> None:
    rows = build_manifest_rows(LISTING_URL, extract_image_candidates("<img src='/photos/a.jpg' alt='a'>", LISTING_URL))
    existing = pd.DataFrame(rows)
    existing.loc[0, "download_status"] = "downloaded"
    existing.loc[0, "image_sha256"] = "abc123"
    existing.loc[0, "content_type"] = "image/jpeg"
    existing.loc[0, "bytes"] = "1234"
    existing.loc[0, "local_path"] = "output/grays_images/cache/a.jpg"

    merged = merge_manifest(existing, rows)

    assert len(merged) == 1
    assert merged.loc[0, "download_status"] == "downloaded"
    assert merged.loc[0, "image_sha256"] == "abc123"
    assert merged.loc[0, "local_path"] == "output/grays_images/cache/a.jpg"


def test_repair_image_links_join_by_listing_url_and_upgrade_when_text_overlaps() -> None:
    manifest = pd.DataFrame(
        [
            {
                "listing_id": "0001-23501266",
                "lot_id": "0001-23501266",
                "listing_url": LISTING_URL,
                "image_url": "https://cdn.example.test/front-bumper-scratched.jpg",
                "position": "1",
                "alt_text": "front bumper scratched",
                "caption": "",
                "local_path": "output/grays_images/cache/a.jpg",
            }
        ]
    )
    repairs = pd.DataFrame(
        [
            {
                "url": LISTING_URL.upper(),
                "repair_key": "front bumper scratched",
                "repair_item": "Front bumper scratched",
                "canonical_defects": "bumper_damage",
                "category": "cosmetic",
                "status": "matched",
            }
        ]
    )

    links = build_repair_image_links(manifest, repairs)

    assert len(links) == 1
    assert links.loc[0, "repair_key"] == "front bumper scratched"
    assert links.loc[0, "match_method"] == "image_text_token_overlap"
    assert links.loc[0, "confidence"] == "medium"


def test_iter_listing_urls_filters_non_grays_and_dedupes(tmp_path) -> None:
    path = tmp_path / "listings.csv"
    pd.DataFrame(
        {
            "url": [
                LISTING_URL,
                LISTING_URL.upper(),
                "https://www.example.com/lot/1",
                "https://www.grays.com/search/automotive-trucks-and-marine/",
            ]
        }
    ).to_csv(path, index=False)

    assert iter_listing_urls([path]) == [LISTING_URL]
