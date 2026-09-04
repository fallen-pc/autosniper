from __future__ import annotations

import pandas as pd
from bs4 import BeautifulSoup

import scripts.extract_vehicle_details as evd


def test_assemble_details_preserves_grays_series_and_drivetrain_identity():
    html = """
    <html>
      <body>
        <h1 class="dls-heading-3">2013 Toyota RAV4 GX Petrol</h1>
        <ul>
          <li>2013 TOYOTA RAV4 GX ASA44R AUTO AWD PETROL SUV 2494cc 132kw 6sp 4cyl 4dr 5seat</li>
          <li>Body Type: SUV</li>
          <li>No. of Seats: 5</li>
          <li>VIN: JTMBFREV605020630</li>
          <li>Fuel Type: Petrol</li>
          <li>Drive Type: Four Wheel Drive</li>
          <li>Transmission: Sports Automatic</li>
          <li>Indicated Odometer Reading: 177321</li>
        </ul>
      </body>
    </html>
    """

    details = evd.assemble_details(
        BeautifulSoup(html, "html.parser"),
        "https://www.grays.com/lot/0012-23502113/motor-vehicles-motor-cycles/2013-toyota-rav4-gx-petrol",
        html,
    )

    assert details["series"] == "asa44r"
    assert details["drivetrain"] == "Four Wheel Drive"


def test_seed_active_dataset_preserves_series_and_drivetrain(monkeypatch, tmp_path):
    active_output_path = tmp_path / "active_vehicle_details.csv"
    monkeypatch.setattr(evd, "ACTIVE_OUTPUT_FILE", active_output_path)
    monkeypatch.setattr(evd, "tag_dataframe", lambda df, **_: df.copy())
    static_df = pd.DataFrame(
        [
            {
                "url": "https://example.test/rav4",
                "series": "asa44r",
                "drivetrain": "four wheel drive",
            }
        ]
    )

    evd.seed_active_dataset(static_df)

    active = pd.read_csv(active_output_path)
    assert active.loc[0, "series"] == "asa44r"
    assert active.loc[0, "drivetrain"] == "four wheel drive"


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
    assert "date_sold" in out_df.columns


def test_extract_details_no_pending_links_leaves_outputs_unchanged(monkeypatch, tmp_path):
    input_path = tmp_path / "active_vehicle_links.csv"
    output_path = tmp_path / "vehicle_static_details.csv"
    active_path = tmp_path / "active_vehicle_details.csv"
    url = "https://example.com/a"

    pd.DataFrame([{"url": url}]).to_csv(input_path, index=False)
    pd.DataFrame([{"url": url, "make": "Toyota"}]).to_csv(output_path, index=False)
    pd.DataFrame([{"url": url, "status": "active"}]).to_csv(active_path, index=False)

    monkeypatch.setattr(evd, "INPUT_FILE", input_path)
    monkeypatch.setattr(evd, "OUTPUT_FILE", output_path)
    monkeypatch.setattr(evd, "ACTIVE_OUTPUT_FILE", active_path)

    calls = {"process": 0}

    def _process_links(_links):
        calls["process"] += 1
        return [], []

    monkeypatch.setattr(evd, "process_links", _process_links)

    evd.main()

    assert calls["process"] == 0
    assert pd.read_csv(output_path).to_dict("records") == [{"url": url, "make": "Toyota"}]


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


def test_read_general_condition_preserves_grays_numbered_assessment_rows():
    html = """
    <html>
      <body>
        <p>The below condition assessment is the opinion of our booking staff which may differ from your own opinion:</p>
        <p>1. Rear End (Rear Bar) - Scratched;Dent(s) under 5cm</p>
        <p>2. Front End (Front Bar) - Scratched</p>
        <p>3. Driver & Passenger Side Wheels - Scratched</p>
        <p>4. Passenger Side (Quarter Panel (Rear Passenger)) - Scratched</p>
        <p>5. Driver Side Driver Door - Dent(s) under 5cm</p>
        <p><strong>Condition</strong></p>
        <ul>
          <li>Scratches And Dents Visible Around Vehicle, Paint Fading Around Vehicle</li>
          <li>Sunglasses Holder Requires Attention, Steering Requires Attention</li>
        </ul>
        <p>Features:</p>
        <p>Reverse camera, bluetooth capability.</p>
      </body>
    </html>
    """
    condition = evd.read_general_condition(BeautifulSoup(html, "html.parser"))

    assert "1. Rear End (Rear Bar) - Scratched;Dent(s) under 5cm" in condition
    assert "3. Driver & Passenger Side Wheels - Scratched" in condition
    assert "Scratches And Dents Visible Around Vehicle, Paint Fading Around Vehicle" in condition
    assert "Sunglasses Holder Requires Attention, Steering Requires Attention" in condition
    assert "Reverse camera" not in condition


def test_read_general_condition_keeps_legacy_condition_list_without_numbered_rows():
    html = """
    <html>
      <body>
        <p><strong>Condition</strong></p>
        <ul>
          <li>Scratches And Dents Visible Around Vehicle</li>
          <li>Windscreen Cracked</li>
        </ul>
      </body>
    </html>
    """
    condition = evd.read_general_condition(BeautifulSoup(html, "html.parser"))

    assert condition == "Scratches And Dents Visible Around Vehicle\nWindscreen Cracked"
