import pandas as pd

import scripts.update_master as update_master


TERMINAL = {"SOLD", "REFERRED", "WITHDRAWN"}


def _update_master_core(
    static_df: pd.DataFrame,
    scraped_status_df: pd.DataFrame,
    prev_urls: set[str],
    curr_urls: set[str],
) -> tuple[pd.DataFrame, set[str]]:
    """Core rule: snapshot-missing is non-terminal; only confirmed terminal statuses prune."""
    missing_urls = prev_urls - curr_urls
    terminal_urls = set(
        scraped_status_df.loc[
            scraped_status_df["status"].isin(TERMINAL), "url"
        ].astype(str)
    )
    pruned_static = static_df[~static_df["url"].astype(str).isin(terminal_urls)].copy()
    return pruned_static, missing_urls


def test_snapshot_missing_does_not_mark_sold_or_prune() -> None:
    missing_url = "https://example.com/lot/123"
    prev_urls = {missing_url}
    curr_urls: set[str] = set()

    static_df = pd.DataFrame(
        {
            "url": [missing_url],
            "status": ["ACTIVE"],
        }
    )

    scraped_status_df = pd.DataFrame(
        {
            "url": [],
            "status": [],
        }
    )

    pruned_static, missing_urls = _update_master_core(
        static_df, scraped_status_df, prev_urls, curr_urls
    )

    assert missing_url in missing_urls
    assert len(pruned_static) == 1
    assert pruned_static.iloc[0]["url"] == missing_url


def test_confirmed_sold_prunes_static() -> None:
    sold_url = "https://example.com/lot/999"

    static_df = pd.DataFrame({"url": [sold_url], "status": ["ACTIVE"]})
    scraped_status_df = pd.DataFrame({"url": [sold_url], "status": ["SOLD"]})

    pruned_static, _ = _update_master_core(
        static_df, scraped_status_df, {sold_url}, set()
    )

    assert len(pruned_static) == 0


def test_sold_rows_missing_sale_price_mask_stays_aligned_when_cleaner_drops_rows() -> None:
    sold_df = pd.DataFrame(
        [
            {
                "url": "https://example.com/lot/1",
                "year": 2020,
                "make": "Toyota",
                "model": "Corolla",
                "price": "10000",
                "time_remaining_or_date_sold": "1 Jan 2025",
                "vin": "JTDKB20U793512345",
            },
            {
                "url": "https://example.com/lot/2",
                "year": "bad",
                "make": "Toyota",
                "model": "Corolla",
                "price": "9000",
                "time_remaining_or_date_sold": "2 Jan 2025",
                "vin": "JTDKB20U793512346",
            },
            {
                "url": "https://example.com/lot/3",
                "year": 2021,
                "make": "Toyota",
                "model": "Corolla",
                "price": "",
                "time_remaining_or_date_sold": "3 Jan 2025",
                "vin": "JTDKB20U793512347",
            },
        ]
    )

    mask = update_master._sold_rows_missing_sale_price(sold_df)

    assert mask.index.tolist() == sold_df.index.tolist()
    assert mask.tolist() == [False, False, True]


def test_update_master_keeps_existing_sold_history_when_url_is_active(monkeypatch, tmp_path) -> None:
    static_path = tmp_path / "vehicle_static_details.csv"
    state_path = tmp_path / "vehicle_state.csv"
    sold_path = tmp_path / "sold_cars.csv"
    referred_path = tmp_path / "referred_cars.csv"
    active_path = tmp_path / "active_vehicle_details.csv"
    active_links_path = tmp_path / "active_vehicle_links.csv"

    url = "https://example.com/lot/123"
    pd.DataFrame(
        [
            {
                "url": url,
                "year": 2020,
                "make": "Toyota",
                "model": "Corolla",
                "variant": "Ascent",
                "vin": "JTDKB20U793512345",
                "location": "VIC",
            }
        ]
    ).to_csv(static_path, index=False)
    pd.DataFrame(
        [
            {
                "url": url,
                "state": "active",
                "current_price": 12000,
                "bid_count": 3,
                "time_remaining": "2h",
                "last_seen_at": "2026-04-05T00:00:00Z",
                "terminal_reason": "",
                "state_updated_at": "2026-04-05T00:00:00Z",
                "fetch_fail_count": 0,
                "last_fetch_error": "",
                "last_evidence": "",
                "run_id": "run-1",
            }
        ]
    ).to_csv(state_path, index=False)
    pd.DataFrame(
        [
            {
                "year": 2020,
                "make": "Toyota",
                "model": "Corolla",
                "variant": "Ascent",
                "vin": "JTDKB20U793512345",
                "location": "VIC",
                "url": url,
                "bids": 8,
                "price": 15000,
                "date_sold": "2025-01-01",
            }
        ]
    ).to_csv(sold_path, index=False)
    pd.DataFrame(columns=["url"]).to_csv(referred_path, index=False)
    pd.DataFrame(columns=["url"]).to_csv(active_path, index=False)
    pd.DataFrame([{"url": url}]).to_csv(active_links_path, index=False)

    monkeypatch.setattr(update_master, "STATIC_FILE", static_path)
    monkeypatch.setattr(update_master, "STATE_FILE", state_path)
    monkeypatch.setattr(update_master, "SOLD_FILE", sold_path)
    monkeypatch.setattr(update_master, "REFERRED_FILE", referred_path)
    monkeypatch.setattr(update_master, "ACTIVE_FILE", active_path)
    monkeypatch.setattr(
        update_master,
        "dataset_path",
        lambda filename: active_links_path if filename == "active_vehicle_links.csv" else tmp_path / filename,
    )
    monkeypatch.setattr(update_master, "normalize_listing_fields", lambda df: df.copy())
    monkeypatch.setattr(update_master, "tag_dataframe", lambda df, **_: df.copy())
    monkeypatch.setattr(update_master, "validate_sold_cars_df", lambda df: (df, {"rows_dropped": 0}))
    monkeypatch.setattr(update_master, "build_restricted_datasets", lambda: None)

    update_master.update_master_database()

    sold_after = pd.read_csv(sold_path)
    assert sold_after["url"].tolist() == [url]
