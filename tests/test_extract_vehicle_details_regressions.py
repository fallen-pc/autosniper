from __future__ import annotations

import pandas as pd

import scripts.extract_vehicle_details as evd


def test_checkpoint_mode_seeds_active_once(monkeypatch, tmp_path):
    input_path = tmp_path / "active_vehicle_links.csv"
    output_path = tmp_path / "vehicle_static_details.csv"
    raw_path = tmp_path / "raw_vehicle_data.csv"
    normal_path = tmp_path / "normalised_data.csv"
    active_path = tmp_path / "active_vehicle_details.csv"

    pd.DataFrame(
        {"url": [f"https://example.com/lot/{idx}" for idx in range(5)]}
    ).to_csv(input_path, index=False)

    monkeypatch.setattr(evd, "INPUT_FILE", input_path)
    monkeypatch.setattr(evd, "OUTPUT_FILE", output_path)
    monkeypatch.setattr(evd, "RAW_OUTPUT_FILE", raw_path)
    monkeypatch.setattr(evd, "NORMALIZED_OUTPUT_FILE", normal_path)
    monkeypatch.setattr(evd, "ACTIVE_OUTPUT_FILE", active_path)

    monkeypatch.setattr(
        evd,
        "process_links",
        lambda links: ([{"url": link} for link in links], []),
    )
    monkeypatch.setattr(evd, "write_skipped", lambda skipped: None)
    monkeypatch.setattr(evd, "_prepare_raw_snapshot", lambda df: df)
    monkeypatch.setattr(evd, "_prepare_normalised_snapshot", lambda df: df)
    monkeypatch.setattr(
        evd,
        "_merge_pipeline_snapshot",
        lambda path, new_df, expected_columns: new_df,
    )
    monkeypatch.setattr(evd, "atomic_write", lambda df, path: None)
    monkeypatch.setattr(
        evd,
        "merge_and_save_static",
        lambda existing_df, new_df: pd.concat([existing_df, new_df], ignore_index=True, sort=False),
    )

    calls = {"seed": 0}

    def _seed_active(static_df):
        calls["seed"] += 1

    monkeypatch.setattr(evd, "seed_active_dataset", _seed_active)

    evd.main(checkpoint_every=2, raw_only=False)
    assert calls["seed"] == 1


def test_seed_active_dataset_handles_duplicate_existing_urls(monkeypatch, tmp_path):
    active_output_path = tmp_path / "active_vehicle_details.csv"
    pd.DataFrame(
        [
            {
                "url": "https://example.com/a",
                "time_remaining_or_date_sold": "x",
                "price": "100",
                "bids": "1",
            },
            {
                "url": "https://EXAMPLE.com/a",
                "time_remaining_or_date_sold": "y",
                "price": "200",
                "bids": "2",
            },
        ]
    ).to_csv(active_output_path, index=False)

    monkeypatch.setattr(evd, "ACTIVE_OUTPUT_FILE", active_output_path)
    monkeypatch.setattr(evd, "tag_dataframe", lambda df, **_: df.copy())

    static_df = pd.DataFrame(
        [
            {
                "url": "https://example.com/a",
                "variant": "variant a",
                "status": "",
                "time_remaining_or_date_sold": "",
                "price": "",
                "bids": "",
            },
            {
                "url": "https://example.com/b",
                "variant": "variant b",
                "status": "",
                "time_remaining_or_date_sold": "",
                "price": "",
                "bids": "",
            },
        ]
    )

    evd.seed_active_dataset(static_df)
    out_df = pd.read_csv(active_output_path)
    assert len(out_df) == 2


def test_append_failure_log_dedupes_without_rewriting(monkeypatch, tmp_path):
    failures_path = tmp_path / "excluded_listings.csv"
    monkeypatch.setattr(evd, "FAILURES_FILE", failures_path)
    monkeypatch.setattr(evd, "_FAILURE_SEEN_KEYS", None)
    monkeypatch.setattr(evd, "append_pipeline_exclusions", lambda records, stage: None)

    records = [
        {
            "timestamp": "2026-03-13 00:00:00",
            "url": "https://example.com/a",
            "reason_code": "BAD_PARSE",
            "field_snapshot": "{}",
        }
    ]
    evd.append_failure_log(records)
    evd.append_failure_log(records)

    out_df = pd.read_csv(failures_path)
    assert len(out_df) == 1
    assert out_df.loc[0, "url"] == "https://example.com/a"


def test_build_canonical_exclusion_failures_preserves_semantics():
    df = pd.DataFrame(
        [
            {
                "url": "https://example.com/ok",
                "canonical_tag": "toyota_camry_ascent_petrol_auto_sedan_asv70r",
                "canonical_reason": "",
                "year": "2020",
            },
            {
                "url": "https://example.com/ambig",
                "canonical_tag": "UNCLASSIFIED",
                "canonical_reason": "AMBIG_BADGE",
                "year": "2018",
            },
            {
                "url": "https://example.com/missing",
                "canonical_tag": "",
                "canonical_reason": "",
                "year": "2016",
            },
        ]
    )
    kept, failures = evd.build_canonical_exclusion_failures(df)
    assert len(kept) == 1
    assert kept.iloc[0]["url"] == "https://example.com/ok"
    assert len(failures) == 2
    by_url = {row["url"]: row for row in failures}
    assert by_url["https://example.com/ambig"]["reason_code"] == "AMBIG_BADGE"
    assert by_url["https://example.com/missing"]["reason_code"] == "NOT_CANONICAL_ELIGIBLE"
