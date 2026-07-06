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


def test_sold_cleaner_keeps_numeric_odometer_from_discrepancy_text() -> None:
    sold_df = pd.DataFrame(
        [
            {
                "url": "https://example.com/lot/odometer-discrepancy",
                "year": 2009,
                "make": "Peugeot",
                "model": "308",
                "price": "2709",
                "date_sold": "07 April 2026 20:00 AEST",
                "bids": 30,
                "odometer_reading": "95435 - Odometer discrepancy detected, see attached history report.",
                "vin": "VF34B5FTF9S104311",
            }
        ]
    )

    cleaned = update_master._prepare_sold_rows(sold_df)

    assert len(cleaned) == 1
    assert int(cleaned.iloc[0]["odometer_reading"]) == 95435
    assert int(cleaned.iloc[0]["odo_suspect"]) == 1


def test_state_sold_current_price_is_not_materialized_as_sale_price() -> None:
    url = "https://example.com/lot/123"
    static_df = pd.DataFrame(
        [
            {
                "url": url,
                "year": 2018,
                "make": "Toyota",
                "model": "Camry",
                "variant": "Ascent",
                "vin": "JTNBF3HK203123456",
            }
        ]
    )
    state_df = pd.DataFrame(
        [
            {
                "url": url,
                "state": "sold",
                "current_price": "209",
                "final_sale_price": "",
                "final_sale_date": "",
                "bid_count": "7",
                "time_remaining": "2026-05-01",
                "last_seen_at": "2026-05-01T00:00:00Z",
            }
        ]
    )

    sold_view = update_master._materialize_state_view(
        static_df,
        state_df,
        target_states={"sold"},
        status_label="sold",
        include_date_sold=True,
    )

    assert sold_view.iloc[0]["price"] == ""
    assert update_master._sold_rows_missing_sale_price(sold_view).tolist() == [True]


def test_state_sold_uses_verified_final_sale_price() -> None:
    url = "https://example.com/lot/456"
    static_df = pd.DataFrame(
        [
            {
                "url": url,
                "year": 2016,
                "make": "Toyota",
                "model": "Camry",
                "variant": "Altise",
                "vin": "6T1BF3FK10X123456",
            }
        ]
    )
    state_df = pd.DataFrame(
        [
            {
                "url": url,
                "state": "sold",
                "current_price": "409",
                "final_sale_price": "9350",
                "final_sale_date": "2026-05-01",
                "bid_count": "11",
                "time_remaining": "2026-05-01",
                "last_seen_at": "2026-05-01T00:00:00Z",
            }
        ]
    )

    sold_view = update_master._materialize_state_view(
        static_df,
        state_df,
        target_states={"sold"},
        status_label="sold",
        include_date_sold=True,
    )

    assert str(sold_view.iloc[0]["price"]) == "9350"
    assert str(sold_view.iloc[0]["date_sold"]) == "2026-05-01"
    assert update_master._sold_rows_missing_sale_price(sold_view).tolist() == [False]


def test_update_master_skips_sold_state_without_verified_final_price(monkeypatch, tmp_path) -> None:
    static_path = tmp_path / "vehicle_static_details.csv"
    state_path = tmp_path / "vehicle_state.csv"
    sold_path = tmp_path / "sold_cars.csv"
    referred_path = tmp_path / "referred_cars.csv"
    active_path = tmp_path / "active_vehicle_details.csv"
    active_links_path = tmp_path / "active_vehicle_links.csv"
    pending_path = tmp_path / "sold_price_pending.csv"
    url = "https://example.com/lot/no-final-price"

    pd.DataFrame(
        [
            {
                "url": url,
                "year": 2018,
                "make": "Toyota",
                "model": "Camry",
                "variant": "Ascent",
                "vin": "6T1BF3FK10X123456",
                "location": "VIC",
            }
        ]
    ).to_csv(static_path, index=False)
    pd.DataFrame(
        [
            {
                "url": url,
                "state": "sold",
                "current_price": "209",
                "final_sale_price": "",
                "final_sale_date": "",
                "bid_count": "7",
                "time_remaining": "2026-05-01",
                "last_seen_at": "2026-05-01T00:00:00Z",
                "terminal_reason": "sold_with_final_price",
                "state_updated_at": "2026-05-01T00:00:00Z",
                "fetch_fail_count": 0,
                "last_fetch_error": "",
                "last_evidence": "legacy_bad_state",
                "run_id": "run-1",
            }
        ]
    ).to_csv(state_path, index=False)
    pd.DataFrame(columns=["url"]).to_csv(sold_path, index=False)
    pd.DataFrame(columns=["url"]).to_csv(referred_path, index=False)
    pd.DataFrame(columns=["url"]).to_csv(active_path, index=False)
    pd.DataFrame(columns=["url"]).to_csv(active_links_path, index=False)

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
    assert sold_after.empty
    assert not pending_path.exists()


def test_update_master_prunes_dead_url_from_active_links(monkeypatch, tmp_path) -> None:
    static_path = tmp_path / "vehicle_static_details.csv"
    state_path = tmp_path / "vehicle_state.csv"
    sold_path = tmp_path / "sold_cars.csv"
    referred_path = tmp_path / "referred_cars.csv"
    active_path = tmp_path / "active_vehicle_details.csv"
    active_links_path = tmp_path / "active_vehicle_links.csv"
    dead_url = "https://example.com/lot/dead"
    live_url = "https://example.com/lot/live"

    pd.DataFrame(
        [
            {"url": dead_url, "year": 2013, "make": "Nissan", "model": "X-Trail", "variant": "ST"},
            {"url": live_url, "year": 2020, "make": "Toyota", "model": "Corolla", "variant": "Ascent"},
        ]
    ).to_csv(static_path, index=False)
    pd.DataFrame(
        [
            {
                "url": dead_url,
                "state": "dead_url",
                "terminal_reason": "dead_url_after_retries",
                "state_updated_at": "2026-07-01T00:00:00Z",
                "fetch_fail_count": 3,
                "last_fetch_error": "no_status_signals",
                "last_evidence": "fetch_failed_no_signals",
                "run_id": "run-1",
            },
            {
                "url": live_url,
                "state": "active",
                "current_price": 1000,
                "bid_count": 1,
                "time_remaining": "2h",
                "terminal_reason": "",
                "state_updated_at": "2026-07-01T00:00:00Z",
                "fetch_fail_count": 0,
                "last_fetch_error": "",
                "last_evidence": "live_countdown_present",
                "run_id": "run-1",
            },
        ]
    ).to_csv(state_path, index=False)
    pd.DataFrame(columns=["url"]).to_csv(sold_path, index=False)
    pd.DataFrame(columns=["url"]).to_csv(referred_path, index=False)
    pd.DataFrame(columns=["url"]).to_csv(active_path, index=False)
    pd.DataFrame([{"url": dead_url}, {"url": live_url}]).to_csv(active_links_path, index=False)

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
    monkeypatch.setattr(update_master, "build_restricted_datasets", lambda: None)

    update_master.update_master_database()

    active_links_after = pd.read_csv(active_links_path)
    assert active_links_after["url"].tolist() == [live_url]


def test_update_master_prunes_terminal_state_from_active_links(monkeypatch, tmp_path) -> None:
    static_path = tmp_path / "vehicle_static_details.csv"
    state_path = tmp_path / "vehicle_state.csv"
    sold_path = tmp_path / "sold_cars.csv"
    referred_path = tmp_path / "referred_cars.csv"
    active_path = tmp_path / "active_vehicle_details.csv"
    active_links_path = tmp_path / "active_vehicle_links.csv"
    sold_url = "https://example.com/lot/sold"
    live_url = "https://example.com/lot/live"

    pd.DataFrame(
        [
            {"url": sold_url, "year": 2013, "make": "Nissan", "model": "X-Trail", "variant": "ST"},
            {"url": live_url, "year": 2020, "make": "Toyota", "model": "Corolla", "variant": "Ascent"},
        ]
    ).to_csv(static_path, index=False)
    pd.DataFrame(
        [
            {
                "url": sold_url,
                "state": "sold",
                "current_price": 6209,
                "final_sale_price": "",
                "final_sale_date": "",
                "bid_count": 78,
                "time_remaining": "",
                "terminal_reason": "sold",
                "state_updated_at": "2026-07-01T00:00:00Z",
                "fetch_fail_count": 0,
                "last_fetch_error": "",
                "last_evidence": "sold_detected",
                "run_id": "run-1",
            },
            {
                "url": live_url,
                "state": "active",
                "current_price": 1000,
                "bid_count": 1,
                "time_remaining": "2h",
                "terminal_reason": "",
                "state_updated_at": "2026-07-01T00:00:00Z",
                "fetch_fail_count": 0,
                "last_fetch_error": "",
                "last_evidence": "live_countdown_present",
                "run_id": "run-1",
            },
        ]
    ).to_csv(state_path, index=False)
    pd.DataFrame(columns=["url"]).to_csv(sold_path, index=False)
    pd.DataFrame(columns=["url"]).to_csv(referred_path, index=False)
    pd.DataFrame(columns=["url"]).to_csv(active_path, index=False)
    pd.DataFrame([{"url": sold_url}, {"url": live_url}]).to_csv(active_links_path, index=False)

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
    monkeypatch.setattr(update_master, "build_restricted_datasets", lambda: None)

    update_master.update_master_database()

    active_links_after = pd.read_csv(active_links_path)
    assert active_links_after["url"].tolist() == [live_url]


def test_update_master_backfills_sold_from_normalized_identity(monkeypatch, tmp_path) -> None:
    static_path = tmp_path / "vehicle_static_details.csv"
    normalized_path = tmp_path / "normalised_data.csv"
    state_path = tmp_path / "vehicle_state.csv"
    sold_path = tmp_path / "sold_cars.csv"
    referred_path = tmp_path / "referred_cars.csv"
    active_path = tmp_path / "active_vehicle_details.csv"
    active_links_path = tmp_path / "active_vehicle_links.csv"
    sold_url = "https://example.com/lot/sold"
    live_url = "https://example.com/lot/live"

    pd.DataFrame(
        [
            {"url": live_url, "year": 2020, "make": "Toyota", "model": "Corolla", "variant": "Ascent"},
        ]
    ).to_csv(static_path, index=False)
    pd.DataFrame(
        [
            {
                "url": sold_url,
                "year": 2013,
                "make": "Toyota",
                "model": "RAV4",
                "variant": "GX Petrol Auto",
                "body_type": "SUV",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "odometer_reading": 258326,
                "vin": "",
                "location": "NSW",
            },
            {
                "url": live_url,
                "year": 2020,
                "make": "Toyota",
                "model": "Corolla",
                "variant": "Ascent",
                "body_type": "Sedan",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "odometer_reading": 80000,
                "vin": "",
                "location": "VIC",
            },
        ]
    ).to_csv(normalized_path, index=False)
    pd.DataFrame(
        [
            {
                "url": sold_url,
                "state": "sold",
                "current_price": 6209,
                "final_sale_price": 6209,
                "final_sale_date": "23 June 2026 20:00 AEST",
                "bid_count": 78,
                "time_remaining": "23 June 2026 20:00 AEST",
                "terminal_reason": "sold_with_final_price",
                "state_updated_at": "2026-07-01T00:00:00Z",
                "fetch_fail_count": 0,
                "last_fetch_error": "",
                "last_evidence": "sold_detected",
                "run_id": "run-1",
            },
            {
                "url": live_url,
                "state": "active",
                "current_price": 1000,
                "bid_count": 1,
                "time_remaining": "2h",
                "terminal_reason": "",
                "state_updated_at": "2026-07-01T00:00:00Z",
                "fetch_fail_count": 0,
                "last_fetch_error": "",
                "last_evidence": "live_countdown_present",
                "run_id": "run-1",
            },
        ]
    ).to_csv(state_path, index=False)
    pd.DataFrame(columns=["url"]).to_csv(sold_path, index=False)
    pd.DataFrame(columns=["url"]).to_csv(referred_path, index=False)
    pd.DataFrame(columns=["url"]).to_csv(active_path, index=False)
    pd.DataFrame([{"url": sold_url}, {"url": live_url}]).to_csv(active_links_path, index=False)

    monkeypatch.setattr(update_master, "STATIC_FILE", static_path)
    monkeypatch.setattr(update_master, "NORMALIZED_FILE", normalized_path)
    monkeypatch.setattr(update_master, "STATE_FILE", state_path)
    monkeypatch.setattr(update_master, "SOLD_FILE", sold_path)
    monkeypatch.setattr(update_master, "REFERRED_FILE", referred_path)
    monkeypatch.setattr(update_master, "ACTIVE_FILE", active_path)
    monkeypatch.setattr(
        update_master,
        "dataset_path",
        lambda filename: active_links_path if filename == "active_vehicle_links.csv" else tmp_path / filename,
    )
    monkeypatch.setattr(update_master, "tag_dataframe", lambda df, **_: df.copy())
    monkeypatch.setattr(update_master, "build_restricted_datasets", lambda: None)

    update_master.update_master_database()

    sold_after = pd.read_csv(sold_path)
    assert sold_after["url"].tolist() == [sold_url]
    assert sold_after.iloc[0]["date_sold"] == "2026-06-23"
    active_links_after = pd.read_csv(active_links_path)
    assert active_links_after["url"].tolist() == [live_url]


def test_update_master_excludes_active_rows_without_price_or_countdown(monkeypatch, tmp_path) -> None:
    static_path = tmp_path / "vehicle_static_details.csv"
    state_path = tmp_path / "vehicle_state.csv"
    sold_path = tmp_path / "sold_cars.csv"
    referred_path = tmp_path / "referred_cars.csv"
    active_path = tmp_path / "active_vehicle_details.csv"
    active_links_path = tmp_path / "active_vehicle_links.csv"
    retry_url = "https://example.com/lot/retry"
    live_url = "https://example.com/lot/live"

    pd.DataFrame(
        [
            {"url": retry_url, "year": 2013, "make": "Nissan", "model": "X-Trail", "variant": "ST"},
            {"url": live_url, "year": 2020, "make": "Toyota", "model": "Corolla", "variant": "Ascent"},
        ]
    ).to_csv(static_path, index=False)
    pd.DataFrame(
        [
            {
                "url": retry_url,
                "state": "active",
                "current_price": "",
                "bid_count": "",
                "time_remaining": "",
                "terminal_reason": "",
                "state_updated_at": "2026-07-01T00:00:00Z",
                "fetch_fail_count": 1,
                "last_fetch_error": "no_status_signals",
                "last_evidence": "fetch_failed_no_signals",
                "run_id": "run-1",
            },
            {
                "url": live_url,
                "state": "active",
                "current_price": 1000,
                "bid_count": 1,
                "time_remaining": "2h",
                "terminal_reason": "",
                "state_updated_at": "2026-07-01T00:00:00Z",
                "fetch_fail_count": 0,
                "last_fetch_error": "",
                "last_evidence": "live_countdown_present",
                "run_id": "run-1",
            },
        ]
    ).to_csv(state_path, index=False)
    pd.DataFrame(columns=["url"]).to_csv(sold_path, index=False)
    pd.DataFrame(columns=["url"]).to_csv(referred_path, index=False)
    pd.DataFrame(columns=["url"]).to_csv(active_path, index=False)
    pd.DataFrame([{"url": retry_url}, {"url": live_url}]).to_csv(active_links_path, index=False)

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
    monkeypatch.setattr(update_master, "build_restricted_datasets", lambda: None)

    update_master.update_master_database()

    active_after = pd.read_csv(active_path)
    assert active_after["url"].tolist() == [live_url]
    active_links_after = pd.read_csv(active_links_path)
    assert active_links_after["url"].tolist() == [retry_url, live_url]


def test_referred_merge_is_url_keyed_even_when_vin_is_blank(tmp_path) -> None:
    referred_path = tmp_path / "referred_cars.csv"
    url = "https://example.com/lot/referred"

    pd.DataFrame(
        [
            {
                "url": url,
                "year": 2018,
                "make": "Toyota",
                "model": "Camry",
                "variant": "Ascent",
                "vin": "6T1BF3FK10X123456",
                "status": "referred",
                "referral_reason": "referred",
            },
            {
                "url": url,
                "year": "",
                "make": "",
                "model": "",
                "variant": "",
                "vin": "",
                "status": "referred",
                "referral_reason": "pre-existing blank duplicate",
            }
        ]
    ).to_csv(referred_path, index=False)
    incoming = pd.DataFrame(
        [
            {
                "url": url,
                "year": "",
                "make": "",
                "model": "",
                "variant": "",
                "vin": "",
                "status": "referred",
                "referral_reason": "late blank row",
            }
        ]
    )

    update_master._merge_preserving_history(
        referred_path,
        incoming,
        "referred/canceled/closed",
        prepare_fn=update_master._prepare_referred_rows,
        ensure_schema=True,
        dedup_keys=("url",),
        dedup_existing=True,
    )

    referred_after = pd.read_csv(referred_path, dtype=str, keep_default_na=False)
    assert referred_after["url"].tolist() == [url]
    assert referred_after.iloc[0]["vin"] == "6T1BF3FK10X123456"


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


def test_prepare_sold_rows_enforces_fixed_sold_schema() -> None:
    frame = pd.DataFrame(
        [
            {
                "year": 2020,
                "make": "Toyota",
                "model": "Corolla",
                "variant": "Ascent",
                "body_type": "Sedan",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "odometer_reading": 120000,
                "no_of_seats": 5,
                "vin": "JTDKB20U793512345",
                "rego_no": "",
                "rego_expiry": "",
                "no_of_cylinders": 4,
                "engine_capacity": 1.8,
                "exterior_colour": "",
                "interior_colour": "",
                "key": "",
                "spare_key": "",
                "owners_manual": "",
                "service_history": "",
                "engine_turns_over": "",
                "location": "VIC",
                "url": "https://example.com/lot/123",
                "general_condition": "",
                "bids": 8,
                "price": 15000,
                "date_sold": "2025-01-01",
                "odo_suspect": 0,
                "canonical_tag": "toyota_corolla_zre172r_sedan_auto_petrol",
                "canonical_reason": "[OK]",
                "price_numeric": 15000,
                "price_text": "$15,000",
                "bids_numeric": 8,
                "odometer_unit": "km",
                "build_date": "2020-01",
                "compliance_date": "2020-02",
                "rego_state": "VIC",
                "no_of_plates": 2,
                "last_observed_price": 12000,
            }
        ]
    )

    prepared = update_master._prepare_sold_rows(frame)

    assert list(prepared.columns) == update_master.SOLD_DETAIL_SCHEMA
    assert "last_observed_price" not in prepared.columns
    assert "odometer_unit" not in prepared.columns
