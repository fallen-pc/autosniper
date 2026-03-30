from __future__ import annotations

from pathlib import Path

from shared.manual_curve_evidence import load_manual_curve_evidence, prepare_manual_curve_evidence


def test_prepare_manual_curve_evidence_standardizes_numeric_fields(tmp_path: Path):
    csv_path = tmp_path / "manual_curve_evidence.csv"
    csv_path.write_text(
        "base_curve_tag,source,year,variant,price,km,engine,body_type,transmission,fuel_type,location,notes\n"
        "hyundai_i30_gd_hatch_auto_petrol,carsales_manual,2014,Elite Auto F MY14,15900,57800,1.8L,hatch,automatic,petrol,VIC,seed row\n",
        encoding="utf-8",
    )

    loaded = load_manual_curve_evidence(csv_path)
    prepared = prepare_manual_curve_evidence(loaded)

    assert len(prepared) == 1
    assert int(prepared.iloc[0]["year_numeric"]) == 2014
    assert int(prepared.iloc[0]["price_numeric"]) == 15900
    assert int(prepared.iloc[0]["odometer_numeric"]) == 57800
    assert prepared.iloc[0]["source_type"] == "carsales_manual"
