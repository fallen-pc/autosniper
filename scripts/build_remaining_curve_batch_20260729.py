"""Build the governed 2026-07-29 Grays-demand curve batch from private Carsales evidence."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from scripts.atomic_csv import write_dataframe_csv_atomic
from shared.curve_builder_v2 import propose_curve_from_evidence
from shared.curves import CURVE_COLUMNS


ROOT = Path(__file__).resolve().parent.parent
RETAIL_PATH = ROOT / "CSV_data" / "scrapers" / "carsales_remaining_targets_batch_20260729.csv"
GRAYS_PATH = ROOT / "CSV_data" / "scrapers" / "sold_cars.csv"
REPORT_PATH = ROOT / "CSV_data" / "model_audit" / "bulk_curve_evidence_20260729.csv"
REJECTION_LEDGER_PATH = ROOT / "notes" / "curve_decisions" / "rejected_curve_lanes.csv"
BUCKETS = [30000, 60000, 100000, 150000, 200000, 225000, 300000]


def lane(
    key: str,
    *,
    make: str,
    retail_model: str,
    config_model: str,
    grays_model: str,
    retail_variant: str,
    grays_variant: str,
    year_min: int,
    year_max: int,
    anchors: list[int],
    badge: str,
    aliases: str,
    series: str,
    engine: str,
    fuel: str,
    base_tag: str,
    match_tag: str,
    excluded: str,
    body: str = "wagon",
    body_aliases: str = "wagon|suv",
    min_retail: int = 10,
    grays_body: str = "",
) -> dict[str, object]:
    return locals()


ALL_LANES = [
    lane("cx3_maxx_sport_dk", make="Mazda", retail_model="CX-3", config_model="cx3", grays_model="CX-3",
         retail_variant=r"^Maxx Sport DK Auto FWD", grays_variant=r"^Maxx Sport \(Fwd\)$",
         year_min=2018, year_max=2023, anchors=[2018, 2020, 2023], badge="maxx sport", aliases="maxx sport",
         series="dk", engine=r"2\.0L", fuel="petrol",
         base_tag="mazda_cx-3_maxx-sport_dk_wagon_auto_petrol",
         match_tag="mazda_cx3_maxx-sport_petrol_auto_wagon_dk",
         excluded="manual|diesel|hybrid|awd|akari|neo|s touring|stouring|g20"),
    lane("cx3_maxx_dk", make="Mazda", retail_model="CX-3", config_model="cx3", grays_model="CX-3",
         retail_variant=r"^Maxx DK Auto$", grays_variant=r"^Maxx \(Fwd\)$",
         year_min=2015, year_max=2018, anchors=[2015, 2017, 2018], badge="maxx", aliases="maxx",
         series="dk", engine=r"2\.0L", fuel="petrol",
         base_tag="mazda_cx-3_maxx_dk_wagon_auto_petrol",
         match_tag="mazda_cx3_maxx_petrol_auto_wagon_dk",
         excluded="manual|diesel|hybrid|awd|maxx sport|akari|neo|s touring|stouring|g20"),
    lane("cx3_stouring_dk", make="Mazda", retail_model="CX-3", config_model="cx3", grays_model="CX-3",
         retail_variant=r"^sTouring DK Auto(?: FWD)?$", grays_variant=r"^(?:S Touring|Stouring) \(Fwd\)$",
         year_min=2015, year_max=2023, anchors=[2015, 2019, 2023], badge="s touring", aliases="s touring|stouring",
         series="dk", engine=r"2\.0L", fuel="petrol",
         base_tag="mazda_cx-3_s-touring_dk_wagon_auto_petrol",
         match_tag="mazda_cx3_s-touring_petrol_auto_wagon_dk",
         excluded="manual|diesel|hybrid|awd|maxx|akari|neo|g20"),
    lane("prado_gxl_3_120", make="Toyota", retail_model="Landcruiser Prado", config_model="landcruiserprado",
         grays_model="Landcruiser Prado", retail_variant=r"^GXL Auto 4x4", grays_variant=r"^Gxl \(4X4\)$",
         year_min=2004, year_max=2009, anchors=[2004, 2007, 2009], badge="gxl", aliases="gxl",
         series="120", engine=r"3\.0L", fuel="diesel",
         base_tag="toyota_landcruiser-prado_gxl_3.0-tdi_120_wagon_auto_diesel",
         match_tag="toyota_landcruiserprado_gxl_diesel_auto_wagon_120",
         excluded="manual|petrol|hybrid|vx|kakadu|gx|altitude"),
    lane("prado_gxl_3_150", make="Toyota", retail_model="Landcruiser Prado", config_model="landcruiserprado",
         grays_model="Landcruiser Prado", retail_variant=r"^GXL Auto 4x4", grays_variant=r"^Gxl \(4X4\)$",
         year_min=2010, year_max=2014, anchors=[2010, 2012, 2014], badge="gxl", aliases="gxl",
         series="150", engine=r"3\.0L", fuel="diesel",
         base_tag="toyota_landcruiser-prado_gxl_3.0-tdi_150_wagon_auto_diesel",
         match_tag="toyota_landcruiserprado_gxl_diesel_auto_wagon_150",
         excluded="manual|petrol|hybrid|vx|kakadu|gx|altitude"),
    lane("prado_gxl_28_150", make="Toyota", retail_model="Landcruiser Prado", config_model="landcruiserprado",
         grays_model="Landcruiser Prado", retail_variant=r"^GXL Auto 4x4", grays_variant=r"^Gxl(?: \(4X4\))?$",
         year_min=2016, year_max=2023, anchors=[2016, 2020, 2023], badge="gxl", aliases="gxl",
         series="150 2.8", engine=r"2\.8L", fuel="diesel",
         base_tag="toyota_landcruiser-prado_gxl_2.8-tdi_150_wagon_auto_diesel",
         match_tag="toyota_landcruiserprado_gxl_diesel_auto_wagon_150-2.8",
         excluded="manual|petrol|hybrid|vx|kakadu|gx|altitude"),
    lane("prado_vx_28_150", make="Toyota", retail_model="Landcruiser Prado", config_model="landcruiserprado",
         grays_model="Landcruiser Prado", retail_variant=r"^VX Auto 4x4", grays_variant=r"^Vx(?: \(4X4\))?$",
         year_min=2016, year_max=2023, anchors=[2016, 2020, 2023], badge="vx", aliases="vx",
         series="150 2.8", engine=r"2\.8L", fuel="diesel",
         base_tag="toyota_landcruiser-prado_vx_2.8-tdi_150_wagon_auto_diesel",
         match_tag="toyota_landcruiserprado_vx_diesel_auto_wagon_150-2.8",
         excluded="manual|petrol|hybrid|gxl|kakadu|gx|altitude"),
    lane("prado_kakadu_28_150", make="Toyota", retail_model="Landcruiser Prado", config_model="landcruiserprado",
         grays_model="Landcruiser Prado", retail_variant=r"^Kakadu Auto 4x4", grays_variant=r"^Kakadu(?: \(4X4\))?$",
         year_min=2016, year_max=2023, anchors=[2016, 2020, 2023], badge="kakadu", aliases="kakadu",
         series="150 2.8", engine=r"2\.8L", fuel="diesel",
         base_tag="toyota_landcruiser-prado_kakadu_2.8-tdi_150_wagon_auto_diesel",
         match_tag="toyota_landcruiserprado_kakadu_diesel_auto_wagon_150-2.8",
         excluded="manual|petrol|hybrid|gxl|vx|gx|altitude"),
    lane("sorento_platinum_um", make="Kia", retail_model="Sorento", config_model="sorento", grays_model="Sorento",
         retail_variant=r"^Platinum Auto AWD", grays_variant=r"^Platinum \(4X4\)$",
         year_min=2015, year_max=2017, anchors=[2015, 2016, 2017], badge="platinum", aliases="platinum",
         series="um", engine=r"2\.2L", fuel="diesel",
         base_tag="kia_sorento_platinum_um_wagon_auto_diesel",
         match_tag="kia_sorento_platinum_diesel_auto_wagon_um",
         excluded="manual|petrol|hybrid|gt line|sport|sli|si|mq4"),
    lane("sorento_gtline_um", make="Kia", retail_model="Sorento", config_model="sorento", grays_model="Sorento",
         retail_variant=r"^GT-Line Auto AWD", grays_variant=r"^Gt-Line \(4X4\)$",
         year_min=2016, year_max=2019, anchors=[2016, 2018, 2019], badge="gt line", aliases="gt line|gt-line",
         series="um", engine=r"2\.2L", fuel="diesel",
         base_tag="kia_sorento_gt-line_um_wagon_auto_diesel",
         match_tag="kia_sorento_gt-line_diesel_auto_wagon_um",
         excluded="manual|petrol|hybrid|platinum|sport|sli|si|mq4"),
    lane("sorento_gtline_mq4", make="Kia", retail_model="Sorento", config_model="sorento", grays_model="Sorento",
         retail_variant=r"^GT-Line Auto AWD", grays_variant=r"^Gt-Line 7 Seat$",
         year_min=2020, year_max=2024, anchors=[2020, 2022, 2024], badge="gt line", aliases="gt line|gt-line",
         series="mq4", engine=r"2\.2L", fuel="diesel",
         base_tag="kia_sorento_gt-line_mq4_wagon_auto_diesel",
         match_tag="kia_sorento_gt-line_diesel_auto_wagon_mq4",
         excluded="manual|petrol|hybrid|platinum|sport|sli|si|um"),
    lane("carnival_s_ka4", make="Kia", retail_model="Carnival", config_model="carnival", grays_model="Carnival",
         retail_variant=r"^S Auto", grays_variant=r"^S$", year_min=2021, year_max=2024,
         anchors=[2021, 2022, 2024], badge="s", aliases="s", series="ka4", engine=r"2\.2L", fuel="diesel",
         base_tag="kia_carnival_s_ka4_people-mover_auto_diesel",
         match_tag="kia_carnival_s_diesel_auto_people-mover_ka4",
         excluded="manual|petrol|hybrid|platinum|sli|si|gt line|sport|yp",
         body="people_mover", body_aliases="people mover|wagon|suv"),
    lane("carnival_platinum_yp", make="Kia", retail_model="Carnival", config_model="carnival", grays_model="Carnival",
         retail_variant=r"^Platinum Auto", grays_variant=r"^Platinum$", year_min=2018, year_max=2020,
         anchors=[2018, 2019, 2020], badge="platinum", aliases="platinum", series="yp",
         engine=r"2\.2L", fuel="diesel",
         base_tag="kia_carnival_platinum_yp_people-mover_auto_diesel",
         match_tag="kia_carnival_platinum_diesel_auto_people-mover_yp",
         excluded="manual|petrol|hybrid|sli|si|gt line|sport|ka4",
         body="people_mover", body_aliases="people mover|wagon|suv"),
    lane("carnival_platinum_ka4", make="Kia", retail_model="Carnival", config_model="carnival", grays_model="Carnival",
         retail_variant=r"^Platinum Auto", grays_variant=r"^Platinum$", year_min=2021, year_max=2023,
         anchors=[2021, 2022, 2023], badge="platinum", aliases="platinum", series="ka4",
         engine=r"2\.2L", fuel="diesel",
         base_tag="kia_carnival_platinum_ka4_people-mover_auto_diesel",
         match_tag="kia_carnival_platinum_diesel_auto_people-mover_ka4",
         excluded="manual|petrol|hybrid|sli|si|gt line|sport|yp",
         body="people_mover", body_aliases="people mover|wagon|suv"),
    lane("santafe_highlander_dm", make="Hyundai", retail_model="Santa Fe", config_model="santafe",
         grays_model="Santa Fe", retail_variant=r"^Highlander Auto 4x4",
         grays_variant=r"^Highlander Crdi \(4X4\)$", year_min=2012, year_max=2017,
         anchors=[2012, 2015, 2017], badge="highlander crdi", aliases="highlander crdi",
         series="dm", engine=r"2\.2L", fuel="diesel",
         base_tag="hyundai_santa-fe_highlander-crdi_dm_wagon_auto_diesel",
         match_tag="hyundai_santafe_highlander-crdi_diesel_auto_wagon_dm",
         excluded="manual|petrol|hybrid|elite|active|calligraphy|tm"),
    lane("santafe_highlander_tm", make="Hyundai", retail_model="Santa Fe", config_model="santafe",
         grays_model="Santa Fe", retail_variant=r"^Highlander Auto 4x4",
         grays_variant=r"^(?:Highlander Crdi(?: Blk-Bge)? \(Awd\)|Highlander Crdi Satin Awd)$",
         year_min=2018, year_max=2020, anchors=[2018, 2019, 2020],
         badge="highlander crdi", aliases="highlander crdi|highlander crdi blk bge|highlander crdi satin awd",
         series="tm", engine=r"2\.2L", fuel="diesel",
         base_tag="hyundai_santa-fe_highlander-crdi_tm_wagon_auto_diesel",
         match_tag="hyundai_santafe_highlander-crdi_diesel_auto_wagon_tm",
         excluded="manual|petrol|hybrid|elite|active|calligraphy|dm"),
    lane("santafe_highlander_tmfl", make="Hyundai", retail_model="Santa Fe", config_model="santafe",
         grays_model="Santa Fe", retail_variant=r"^Highlander Auto 4x4",
         grays_variant=r"^Highlander Crdi \(Awd\)$", year_min=2021, year_max=2023,
         anchors=[2021, 2022, 2023], badge="highlander crdi", aliases="highlander crdi",
         series="tmfl", engine=r"2\.2L", fuel="diesel",
         base_tag="hyundai_santa-fe_highlander-crdi_tmfl_wagon_auto_diesel",
         match_tag="hyundai_santafe_highlander-crdi_diesel_auto_wagon_tmfl",
         excluded="manual|petrol|hybrid|elite|active|calligraphy|dm"),
    lane("asx_ls_xb", make="Mitsubishi", retail_model="ASX", config_model="asx", grays_model="ASX",
         retail_variant=r"^LS XB Auto 2WD", grays_variant=r"^Ls \(2Wd\)$",
         year_min=2014, year_max=2016, anchors=[2014, 2015, 2016], badge="ls", aliases="ls",
         series="xb", engine=r"2\.0L", fuel="petrol",
         base_tag="mitsubishi_asx_ls_xb_wagon_auto_petrol",
         match_tag="mitsubishi_asx_ls_petrol_auto_wagon_xb",
         excluded="manual|diesel|hybrid|xls|exceed|es|mr|gsr|xc|xd"),
    lane("asx_ls_xc", make="Mitsubishi", retail_model="ASX", config_model="asx", grays_model="ASX",
         retail_variant=r"^LS XC Auto 2WD", grays_variant=r"^Ls \(2Wd\)$",
         year_min=2017, year_max=2019, anchors=[2017, 2018, 2019], badge="ls", aliases="ls",
         series="xc", engine=r"2\.0L", fuel="petrol",
         base_tag="mitsubishi_asx_ls_xc_wagon_auto_petrol",
         match_tag="mitsubishi_asx_ls_petrol_auto_wagon_xc",
         excluded="manual|diesel|hybrid|xls|exceed|es|mr|gsr|xb|xd"),
    lane("asx_es_xd", make="Mitsubishi", retail_model="ASX", config_model="asx", grays_model="ASX",
         retail_variant=r"^ES XD Auto 2WD", grays_variant=r"^Es \(2Wd\)$",
         year_min=2020, year_max=2024, anchors=[2020, 2022, 2024], badge="es", aliases="es",
         series="xd", engine=r"2\.0L", fuel="petrol",
         base_tag="mitsubishi_asx_es_xd_wagon_auto_petrol",
         match_tag="mitsubishi_asx_es_petrol_auto_wagon_xd",
         excluded="manual|diesel|hybrid|adas|plus|ls|xls|exceed|mr|gsr|xb|xc"),
]

ALL_LANES += [
    lane("bt50_xtr_ur", make="Mazda", retail_model="BT-50", config_model="bt50", grays_model="BT-50",
         retail_variant=r"^XTR UR Auto 4x4 Dual Cab", grays_variant=r"^Xtr \(4X4\)$",
         year_min=2016, year_max=2020, anchors=[2016, 2018, 2020], badge="xtr", aliases="xtr",
         series="ur", engine=r"3\.2L", fuel="diesel",
         base_tag="mazda_bt-50_xtr_ur_dualcab-auto-diesel",
         match_tag="mazda_bt50_xtr_diesel_auto_dualcab-ute_ur",
         excluded="manual|petrol|hybrid|4x2|2wd|xt|gt|sp|tf|up",
         body="dualcab_ute", body_aliases="dual cab utility|dual cab pick up|ute"),
    lane("mazda2_neo_de", make="Mazda", retail_model="2", config_model="2", grays_model="2",
         retail_variant=r"^Neo DE Series [12] Auto", grays_variant=r"^Neo$",
         year_min=2008, year_max=2013, anchors=[2008, 2011, 2013], badge="neo", aliases="neo",
         series="de", engine=r"1\.5L", fuel="petrol",
         base_tag="mazda_2_neo_de_hatch_auto_petrol",
         match_tag="mazda_2_neo_petrol_auto_hatch_de",
         excluded="manual|diesel|hybrid|neo sport|maxx|genki|dj|sedan",
         body="hatch", body_aliases="hatch|hatchback"),
    lane("mazda2_maxx_dj", make="Mazda", retail_model="2", config_model="2", grays_model="2",
         retail_variant=r"^Maxx DJ Series Auto", grays_variant=r"^Maxx(?: \(5Yr\))?$",
         year_min=2014, year_max=2019, anchors=[2014, 2017, 2019], badge="maxx", aliases="maxx",
         series="dj", engine=r"1\.5L", fuel="petrol",
         base_tag="mazda_2_maxx_dj_hatch_auto_petrol",
         match_tag="mazda_2_maxx_petrol_auto_hatch_dj",
         excluded="manual|diesel|hybrid|neo|genki|de|sedan",
         body="hatch", body_aliases="hatch|hatchback"),
    lane("pajero_sport_exceed_qe", make="Mitsubishi", retail_model="Pajero Sport", config_model="pajerosport",
         grays_model="Pajero Sport", retail_variant=r"^Exceed QE Auto 4x4",
         grays_variant=r"^Exceed \(4X4\) 7 Seat$", year_min=2015, year_max=2019,
         anchors=[2015, 2017, 2019], badge="exceed", aliases="exceed", series="qe",
         engine=r"2\.4L", fuel="diesel",
         base_tag="mitsubishi_pajero-sport_exceed_qe_wagon_auto_diesel",
         match_tag="mitsubishi_pajerosport_exceed_diesel_auto_wagon_qe",
         excluded="manual|petrol|hybrid|gls|glx|gsr|black edition|qf"),
    lane("pajero_sport_exceed_qf", make="Mitsubishi", retail_model="Pajero Sport", config_model="pajerosport",
         grays_model="Pajero Sport", retail_variant=r"^Exceed QF Auto 4x4",
         grays_variant=r"^Exceed \(4Wd\) 7 Seat$", year_min=2020, year_max=2025,
         anchors=[2020, 2022, 2025], badge="exceed", aliases="exceed", series="qf",
         engine=r"2\.4L", fuel="diesel",
         base_tag="mitsubishi_pajero-sport_exceed_qf_wagon_auto_diesel",
         match_tag="mitsubishi_pajerosport_exceed_diesel_auto_wagon_qf",
         excluded="manual|petrol|hybrid|gls|glx|gsr|black edition|qe"),
    lane("pajero_sport_gls_qe", make="Mitsubishi", retail_model="Pajero Sport", config_model="pajerosport",
         grays_model="Pajero Sport", retail_variant=r"^GLS QE Auto 4x4",
         grays_variant=r"^Gls \(4X4\)(?: 7 Seat)?$", year_min=2015, year_max=2019,
         anchors=[2015, 2017, 2019], badge="gls", aliases="gls", series="qe",
         engine=r"2\.4L", fuel="diesel",
         base_tag="mitsubishi_pajero-sport_gls_qe_wagon_auto_diesel",
         match_tag="mitsubishi_pajerosport_gls_diesel_auto_wagon_qe",
         excluded="manual|petrol|hybrid|exceed|glx|gsr|black edition|qf"),
    lane("pajero_sport_gls_qf", make="Mitsubishi", retail_model="Pajero Sport", config_model="pajerosport",
         grays_model="Pajero Sport", retail_variant=r"^GLS QF Auto 4x4",
         grays_variant=r"^Gls \(4Wd\) 7 Seat$", year_min=2020, year_max=2025,
         anchors=[2020, 2022, 2025], badge="gls", aliases="gls", series="qf",
         engine=r"2\.4L", fuel="diesel",
         base_tag="mitsubishi_pajero-sport_gls_qf_wagon_auto_diesel",
         match_tag="mitsubishi_pajerosport_gls_diesel_auto_wagon_qf",
         excluded="manual|petrol|hybrid|exceed|glx|gsr|black edition|qe"),
    lane("chr_koba_2wd", make="Toyota", retail_model="C-HR", config_model="chr", grays_model="C-HR",
         retail_variant=r"^Koba Auto 2WD$", grays_variant=r"^Koba \(2Wd\)$",
         year_min=2017, year_max=2023, anchors=[2017, 2020, 2023], badge="koba", aliases="koba",
         series="2wd", engine=r"1\.2L", fuel="petrol",
         base_tag="toyota_c-hr_koba_2wd_wagon_auto_petrol",
         match_tag="toyota_chr_koba_petrol_auto_wagon_2wd",
         excluded="manual|diesel|hybrid|awd|gr sport|gxl"),
    lane("chr_koba_awd", make="Toyota", retail_model="C-HR", config_model="chr", grays_model="C-HR",
         retail_variant=r"^Koba Auto AWD$", grays_variant=r"^Koba \(Awd\)$",
         year_min=2017, year_max=2023, anchors=[2017, 2020, 2023], badge="koba", aliases="koba",
         series="awd", engine=r"1\.2L", fuel="petrol",
         base_tag="toyota_c-hr_koba_awd_wagon_auto_petrol",
         match_tag="toyota_chr_koba_petrol_auto_wagon_awd",
         excluded="manual|diesel|hybrid|2wd|gr sport|gxl"),
    lane("chr_koba_hybrid", make="Toyota", retail_model="C-HR", config_model="chr", grays_model="C-HR",
         retail_variant=r"^Koba Auto (?:2WD)?$", grays_variant=r"^Koba \(2Wd\) Hybrid$",
         year_min=2020, year_max=2023, anchors=[2020, 2021, 2023], badge="koba hybrid",
         aliases="koba|koba hybrid", series="hybrid", engine=r"1\.8L", fuel="hybrid",
         base_tag="toyota_c-hr_koba_2wd_wagon_auto_hybrid",
         match_tag="toyota_chr_koba-hybrid_hybrid_auto_wagon_2wd",
         excluded="manual|diesel|petrol|awd|gr sport|gxl"),
    lane("eclipse_exceed_ya", make="Mitsubishi", retail_model="Eclipse Cross",
         config_model="eclipsecross", grays_model="Eclipse Cross",
         retail_variant=r"^Exceed YA Auto 2WD", grays_variant=r"^Exceed \(2Wd\)$",
         year_min=2017, year_max=2020, anchors=[2017, 2018, 2020], badge="exceed", aliases="exceed",
         series="ya", engine=r"1\.5L", fuel="petrol",
         base_tag="mitsubishi_eclipse-cross_exceed_ya_wagon_auto_petrol",
         match_tag="mitsubishi_eclipsecross_exceed_petrol_auto_wagon_ya",
         excluded="manual|diesel|hybrid|phev|awd|ls|es|aspire|yb"),
    lane("eclipse_ls_ya", make="Mitsubishi", retail_model="Eclipse Cross",
         config_model="eclipsecross", grays_model="Eclipse Cross",
         retail_variant=r"^LS YA Auto 2WD", grays_variant=r"^Ls \(2Wd\)$",
         year_min=2017, year_max=2020, anchors=[2017, 2018, 2020], badge="ls", aliases="ls",
         series="ya", engine=r"1\.5L", fuel="petrol",
         base_tag="mitsubishi_eclipse-cross_ls_ya_wagon_auto_petrol",
         match_tag="mitsubishi_eclipsecross_ls_petrol_auto_wagon_ya",
         excluded="manual|diesel|hybrid|phev|awd|exceed|es|aspire|yb"),
    lane("eclipse_es_yb", make="Mitsubishi", retail_model="Eclipse Cross",
         config_model="eclipsecross", grays_model="Eclipse Cross",
         retail_variant=r"^ES YB Auto 2WD", grays_variant=r"^Es \(2Wd\)$",
         year_min=2020, year_max=2025, anchors=[2020, 2022, 2025], badge="es", aliases="es",
         series="yb", engine=r"1\.5L", fuel="petrol",
         base_tag="mitsubishi_eclipse-cross_es_yb_wagon_auto_petrol",
         match_tag="mitsubishi_eclipsecross_es_petrol_auto_wagon_yb",
         excluded="manual|diesel|hybrid|phev|awd|exceed|ls|aspire|ya", min_retail=7),
    lane("kona_active_os", make="Hyundai", retail_model="Kona", config_model="kona", grays_model="Kona",
         retail_variant=r"^Active Auto 2WD", grays_variant=r"^Active(?: \(Fwd\))?$",
         year_min=2017, year_max=2021, anchors=[2017, 2019, 2021], badge="active", aliases="active",
         series="os", engine=r"2\.0L", fuel="petrol",
         base_tag="hyundai_kona_active_os_wagon_auto_petrol",
         match_tag="hyundai_kona_active_petrol_auto_wagon_os",
         excluded="manual|diesel|hybrid|electric|awd|elite|go|highlander|n line|premium"),
    lane("dmax_xterrain_rg", make="Isuzu", retail_model="D-MAX", config_model="dmax", grays_model="D-MAX",
         retail_variant=r"^X-TERRAIN Auto 4x4", grays_variant=r"^X-Terrain \(4X4\)$",
         year_min=2020, year_max=2025, anchors=[2020, 2022, 2025], badge="x terrain",
         aliases="x terrain|x-terrain", series="rg", engine=r"3\.0L", fuel="diesel",
         base_tag="isuzu_d-max_x-terrain_rg_dualcab-auto-diesel",
         match_tag="isuzu_dmax_x-terrain_diesel_auto_dualcab-ute_rg",
         excluded="manual|petrol|hybrid|4x2|2wd|ls u|ls m|sx|x rider",
         body="dualcab_ute", body_aliases="crew cab utility|dual cab utility|dual cab pick up|ute"),
    lane("qashqai_st_j11", make="Nissan", retail_model="QASHQAI", config_model="qashqai",
         grays_model="QASHQAI", retail_variant=r"^ST J11 Auto$", grays_variant=r"^St \(4X2\)$",
         year_min=2014, year_max=2017, anchors=[2014, 2016, 2017], badge="st", aliases="st",
         series="j11", engine=r"2\.0L", fuel="petrol",
         base_tag="nissan_qashqai_st_j11_wagon_auto_petrol",
         match_tag="nissan_qashqai_st_petrol_auto_wagon_j11",
         excluded="manual|diesel|hybrid|ti|st l|st-l|n tec|j12|series 2|series 3"),
    lane("qashqai_ti_j11", make="Nissan", retail_model="QASHQAI", config_model="qashqai",
         grays_model="QASHQAI", retail_variant=r"^Ti J11 Auto$", grays_variant=r"^Ti \(4X2\)$",
         year_min=2014, year_max=2017, anchors=[2014, 2016, 2017], badge="ti", aliases="ti",
         series="j11", engine=r"2\.0L", fuel="petrol",
         base_tag="nissan_qashqai_ti_j11_wagon_auto_petrol",
         match_tag="nissan_qashqai_ti_petrol_auto_wagon_j11",
         excluded="manual|diesel|hybrid|st|n tec|j12|series 2|series 3"),
    lane("qashqai_st_j11s2", make="Nissan", retail_model="QASHQAI", config_model="qashqai",
         grays_model="QASHQAI", retail_variant=r"^ST J11 Series [23] Auto", grays_variant=r"^St$",
         year_min=2017, year_max=2021, anchors=[2017, 2019, 2021], badge="st", aliases="st",
         series="j11 series 2", engine=r"2\.0L", fuel="petrol",
         base_tag="nissan_qashqai_st_j11-series2_wagon_auto_petrol",
         match_tag="nissan_qashqai_st_petrol_auto_wagon_j11-series2",
         excluded="manual|diesel|hybrid|ti|st l|st-l|n tec|j12"),
    lane("qashqai_ti_j11s2", make="Nissan", retail_model="QASHQAI", config_model="qashqai",
         grays_model="QASHQAI", retail_variant=r"^Ti J11 Series [23] Auto", grays_variant=r"^Ti$",
         year_min=2018, year_max=2021, anchors=[2018, 2019, 2021], badge="ti", aliases="ti",
         series="j11 series 2", engine=r"2\.0L", fuel="petrol",
         base_tag="nissan_qashqai_ti_j11-series2_wagon_auto_petrol",
         match_tag="nissan_qashqai_ti_petrol_auto_wagon_j11-series2",
         excluded="manual|diesel|hybrid|st|n tec|j12"),
]

ALL_LANES += [
    lane("sportage_gtline_diesel_ql", make="Kia", retail_model="Sportage", config_model="sportage",
         grays_model="Sportage", retail_variant=r"^GT-Line Auto AWD", grays_variant=r"^Gt-Line \(Awd\)$",
         year_min=2016, year_max=2020, anchors=[2016, 2018, 2020], badge="gt line", aliases="gt line|gt-line",
         series="ql diesel", engine=r"2\.0L", fuel="diesel",
         base_tag="kia_sportage_gt-line_ql_wagon_auto_diesel",
         match_tag="kia_sportage_gt-line_diesel_auto_wagon_ql",
         excluded="manual|petrol|hybrid|s|sx|si|platinum|nq5"),
    lane("sportage_gtline_diesel_nq5", make="Kia", retail_model="Sportage", config_model="sportage",
         grays_model="Sportage", retail_variant=r"^GT-Line Auto AWD", grays_variant=r"^Gt-Line \(Awd\)$",
         year_min=2021, year_max=2025, anchors=[2021, 2023, 2025], badge="gt line", aliases="gt line|gt-line",
         series="nq5 diesel", engine=r"2\.0L", fuel="diesel",
         base_tag="kia_sportage_gt-line_nq5_wagon_auto_diesel",
         match_tag="kia_sportage_gt-line_diesel_auto_wagon_nq5",
         excluded="manual|petrol|hybrid|s|sx|si|platinum|ql"),
    lane("sportage_gtline_petrol_ql", make="Kia", retail_model="Sportage", config_model="sportage",
         grays_model="Sportage", retail_variant=r"^GT-Line Auto AWD", grays_variant=r"^Gt-Line \(Awd\)$",
         year_min=2016, year_max=2020, anchors=[2016, 2018, 2020], badge="gt line", aliases="gt line|gt-line",
         series="ql petrol", engine=r"2\.4L", fuel="petrol",
         base_tag="kia_sportage_gt-line_ql_wagon_auto_petrol",
         match_tag="kia_sportage_gt-line_petrol_auto_wagon_ql",
         excluded="manual|diesel|hybrid|s|sx|si|platinum|nq5", min_retail=8),
    lane("sportage_gtline_petrol_nq5", make="Kia", retail_model="Sportage", config_model="sportage",
         grays_model="Sportage", retail_variant=r"^GT-Line Auto AWD", grays_variant=r"^Gt-Line \(Awd\)$",
         year_min=2021, year_max=2025, anchors=[2021, 2023, 2025], badge="gt line", aliases="gt line|gt-line",
         series="nq5 petrol", engine=r"1\.6L", fuel="petrol",
         base_tag="kia_sportage_gt-line_nq5_wagon_auto_petrol",
         match_tag="kia_sportage_gt-line_petrol_auto_wagon_nq5",
         excluded="manual|diesel|hybrid|s|sx|si|platinum|ql"),
    lane("sportage_s_nq5", make="Kia", retail_model="Sportage", config_model="sportage",
         grays_model="Sportage", retail_variant=r"^S Auto FWD", grays_variant=r"^S \(Fwd\)$",
         year_min=2021, year_max=2025, anchors=[2021, 2023, 2025], badge="s", aliases="s",
         series="nq5", engine=r"2\.0L", fuel="petrol",
         base_tag="kia_sportage_s_nq5_wagon_auto_petrol",
         match_tag="kia_sportage_s_petrol_auto_wagon_nq5",
         excluded="manual|diesel|hybrid|awd|sx|si|gt line|platinum|ql", min_retail=8),
    lane("hiace_lwb_28_h300", make="Toyota", retail_model="Hiace", config_model="hiace", grays_model="Hiace",
         retail_variant=r"^LWB Auto$", grays_variant=r"^Lwb(?: \(4 Door Option\)| Gl \(Colours\))?$",
         year_min=2019, year_max=2026, anchors=[2019, 2022, 2026], badge="lwb", aliases="lwb|lwb 4 door option|lwb gl colours",
         series="h300 2.8", engine=r"2\.8L", fuel="diesel",
         base_tag="toyota_hiace_lwb_2.8-tdi_h300_van_auto_diesel",
         match_tag="toyota_hiace_lwb_diesel_auto_van_h300",
         excluded="manual|petrol|hybrid|slwb|commuter|super lwb|3.0",
         body="van", body_aliases="van|commercial"),
    lane("hiace_lwb_30_h200", make="Toyota", retail_model="Hiace", config_model="hiace", grays_model="Hiace",
         retail_variant=r"^LWB Auto$", grays_variant=r"^Lwb$", year_min=2012, year_max=2018,
         anchors=[2012, 2015, 2018], badge="lwb", aliases="lwb", series="h200 3.0",
         engine=r"3\.0L", fuel="diesel",
         base_tag="toyota_hiace_lwb_3.0-tdi_h200_van_auto_diesel",
         match_tag="toyota_hiace_lwb_diesel_auto_van_h200",
         excluded="manual|petrol|hybrid|slwb|commuter|super lwb|2.8",
         body="van", body_aliases="van|commercial"),
    lane("hiace_slwb_28_h300", make="Toyota", retail_model="Hiace", config_model="hiace", grays_model="Hiace",
         retail_variant=r"^Super LWB Auto$", grays_variant=r"^Slwb$", year_min=2020, year_max=2025,
         anchors=[2020, 2022, 2025], badge="slwb", aliases="slwb", series="h300 2.8",
         engine=r"2\.8L", fuel="diesel",
         base_tag="toyota_hiace_slwb_2.8-tdi_h300_van_auto_diesel",
         match_tag="toyota_hiace_slwb_diesel_auto_van_h300",
         excluded="manual|petrol|hybrid|lwb|commuter|3.0",
         body="van", body_aliases="van|commercial"),
    lane("hiace_commuter_28_h300", make="Toyota", retail_model="Hiace", config_model="hiace", grays_model="Hiace",
         retail_variant=r"^Commuter Super LWB Auto$", grays_variant=r"^(?:Slwb Commuter \(12 Seats\)|Gdh320r)$",
         year_min=2019, year_max=2024, anchors=[2019, 2022, 2024], badge="slwb commuter",
         aliases="slwb commuter|slwb commuter 12 seats|gdh320r", series="gdh320r", engine=r"2\.8L", fuel="diesel",
         base_tag="toyota_hiace_commuter-slwb_2.8-tdi_h300_bus_auto_diesel",
         match_tag="toyota_hiace_slwb-commuter_diesel_auto_bus_h300",
         excluded="manual|petrol|hybrid|lwb|3.0", body="bus", body_aliases="bus"),
    lane("landcruiser_gxl_200", make="Toyota", retail_model="Landcruiser", config_model="landcruiser",
         grays_model="Landcruiser", retail_variant=r"^GXL Auto 4x4(?: MY13)?$",
         grays_variant=r"^(?:Lc200 )?Gxl \(4X4\)$", year_min=2007, year_max=2021,
         anchors=[2007, 2014, 2021], badge="gxl", aliases="gxl|lc200 gxl", series="lc200",
         engine=r"4\.5L", fuel="diesel",
         base_tag="toyota_landcruiser_gxl_200_wagon_auto_diesel",
         match_tag="toyota_landcruiser_gxl_diesel_auto_wagon_200",
         excluded="manual|petrol|hybrid|vx|sahara|workmate|lc300"),
    lane("landcruiser_vx_200", make="Toyota", retail_model="Landcruiser", config_model="landcruiser",
         grays_model="Landcruiser", retail_variant=r"^VX Auto 4x4$", grays_variant=r"^(?:Lc200 )?Vx \(4X4\)$",
         year_min=2008, year_max=2021, anchors=[2008, 2015, 2021], badge="vx", aliases="vx|lc200 vx",
         series="lc200", engine=r"4\.5L", fuel="diesel",
         base_tag="toyota_landcruiser_vx_200_wagon_auto_diesel",
         match_tag="toyota_landcruiser_vx_diesel_auto_wagon_200",
         excluded="manual|petrol|hybrid|gxl|sahara|workmate|lc300"),
    lane("landcruiser_sahara_200", make="Toyota", retail_model="Landcruiser", config_model="landcruiser",
         grays_model="Landcruiser", retail_variant=r"^Sahara Auto 4x4", grays_variant=r"^(?:Lc200 )?Sahara \(4X4\)$",
         year_min=2008, year_max=2021, anchors=[2008, 2015, 2021], badge="sahara",
         aliases="sahara|lc200 sahara", series="lc200", engine=r"4\.5L", fuel="diesel",
         base_tag="toyota_landcruiser_sahara_200_wagon_auto_diesel",
         match_tag="toyota_landcruiser_sahara_diesel_auto_wagon_200",
         excluded="manual|petrol|hybrid|gxl|vx|workmate|lc300"),
    lane("landcruiser_vx_300", make="Toyota", retail_model="Landcruiser", config_model="landcruiser",
         grays_model="Landcruiser", retail_variant=r"^VX Auto 4x4$", grays_variant=r"^Lc300 Vx \(4X4\)$",
         year_min=2021, year_max=2026, anchors=[2021, 2023, 2026], badge="lc300 vx",
         aliases="lc300 vx", series="lc300", engine=r"3\.3L", fuel="diesel",
         base_tag="toyota_landcruiser_vx_300_wagon_auto_diesel",
         match_tag="toyota_landcruiser_lc300-vx_diesel_auto_wagon_300",
         excluded="manual|petrol|hybrid|gxl|sahara|workmate|lc200", min_retail=8),
    lane("mustang_gt_fm", make="Ford", retail_model="Mustang", config_model="mustang", grays_model="Mustang",
         retail_variant=r"^GT FM Auto", grays_variant=r"^Fastback Gt 5.0 V8$",
         year_min=2015, year_max=2017, anchors=[2015, 2016, 2017], badge="fastback gt 5.0 v8",
         aliases="fastback gt 5.0 v8", series="fm", engine=r"5\.0L", fuel="petrol",
         base_tag="ford_mustang_gt-5.0_fm_coupe_auto_petrol",
         match_tag="ford_mustang_fastback-gt-5.0-v8_petrol_auto_coupe_fm",
         excluded="manual|diesel|hybrid|ecoboost|convertible|fn|fo", body="coupe", body_aliases="coupe|fastback"),
    lane("mustang_gt_fn", make="Ford", retail_model="Mustang", config_model="mustang", grays_model="Mustang",
         retail_variant=r"^GT FN Auto", grays_variant=r"^Gt 5.0 V8$", year_min=2018, year_max=2023,
         anchors=[2018, 2020, 2023], badge="gt 5.0 v8", aliases="gt 5.0 v8", series="fn",
         engine=r"5\.0L", fuel="petrol",
         base_tag="ford_mustang_gt-5.0_fn_coupe_auto_petrol",
         match_tag="ford_mustang_gt-5.0-v8_petrol_auto_coupe_fn",
         excluded="manual|diesel|hybrid|ecoboost|convertible|fm|fo", body="coupe",
         body_aliases="coupe|fastback"),
    lane("grand_cherokee_laredo_wk_diesel", make="Jeep", retail_model="Grand Cherokee",
         config_model="grandcherokee", grays_model="Grand Cherokee",
         retail_variant=r"^Laredo Auto 4x4", grays_variant=r"^Laredo \(4X4\)$",
         year_min=2012, year_max=2018, anchors=[2012, 2015, 2018], badge="laredo",
         aliases="laredo", series="wk diesel", engine=r"3\.0L", fuel="diesel",
         base_tag="jeep_grand-cherokee_laredo-wk_4x4_wagon_auto_diesel",
         match_tag="jeep_grandcherokee_laredo_diesel_auto_wagon_wk",
         excluded="manual|petrol|hybrid|4x2|limited|overland|night eagle|wl"),
    lane("grand_cherokee_limited_wk_diesel", make="Jeep", retail_model="Grand Cherokee",
         config_model="grandcherokee", grays_model="Grand Cherokee",
         retail_variant=r"^Limited Auto 4x4", grays_variant=r"^Limited \(4X4\)$",
         year_min=2011, year_max=2019, anchors=[2011, 2015, 2019], badge="limited",
         aliases="limited", series="wk diesel", engine=r"3\.0L", fuel="diesel",
         base_tag="jeep_grand-cherokee_limited-wk_4x4_wagon_auto_diesel",
         match_tag="jeep_grandcherokee_limited_diesel_auto_wagon_wk",
         excluded="manual|petrol|hybrid|4x2|laredo|overland|night eagle|wl"),
    lane("grand_cherokee_limited_wk_petrol", make="Jeep", retail_model="Grand Cherokee",
         config_model="grandcherokee", grays_model="Grand Cherokee",
         retail_variant=r"^Limited Auto 4x4", grays_variant=r"^Limited \(4X4\)$",
         year_min=2013, year_max=2021, anchors=[2013, 2017, 2021], badge="limited",
         aliases="limited", series="wk petrol", engine=r"3\.6L", fuel="petrol",
         base_tag="jeep_grand-cherokee_limited-wk_4x4_wagon_auto_petrol",
         match_tag="jeep_grandcherokee_limited_petrol_auto_wagon_wk",
         excluded="manual|diesel|hybrid|4x2|laredo|overland|night eagle|wl"),
    lane("mg3_core_szp1", make="MG", retail_model="MG3", config_model="mg3", grays_model="MG3",
         retail_variant=r"^Core(?: \(Nav\))? Auto", grays_variant=r"^Core(?: \(With Navigation\))?$",
         year_min=2019, year_max=2024, anchors=[2019, 2022, 2024], badge="core", aliases="core|core with navigation",
         series="szp1", engine=r"1\.5L", fuel="petrol",
         base_tag="mg_mg3_core_szp1_hatch_auto_petrol",
         match_tag="mg_mg3_core_petrol_auto_hatch_szp1",
         excluded="manual|diesel|hybrid|excite|essence", body="hatch", body_aliases="hatch|hatchback"),
    lane("mg3_excite_szp1", make="MG", retail_model="MG3", config_model="mg3", grays_model="MG3",
         retail_variant=r"^Excite Auto", grays_variant=r"^Excite(?: \(With Navigation\))?$",
         year_min=2018, year_max=2024, anchors=[2018, 2021, 2024], badge="excite",
         aliases="excite|excite with navigation", series="szp1", engine=r"1\.5L", fuel="petrol",
         base_tag="mg_mg3_excite_szp1_hatch_auto_petrol",
         match_tag="mg_mg3_excite_petrol_auto_hatch_szp1",
         excluded="manual|diesel|hybrid|core|essence", body="hatch", body_aliases="hatch|hatchback"),
    lane("amarok_tdi580_highline_2h", make="Volkswagen", retail_model="Amarok", config_model="amarok",
         grays_model="Amarok", retail_variant=r"^TDI580 Highline(?: Black)? 2H Auto",
         grays_variant=r"^Tdi580 Highline 4Motion$", year_min=2019, year_max=2022,
         anchors=[2019, 2021, 2022], badge="tdi580 highline", aliases="tdi580 highline",
         series="tdi580", engine=r"3\.0L", fuel="diesel",
         base_tag="volkswagen_amarok_tdi580-highline_2h_dualcab-auto-diesel",
         match_tag="volkswagen_amarok_tdi580-highline_diesel_auto_dualcab-ute_2h",
         excluded="manual|petrol|hybrid|tdi420|tdi550|tdi600|black edition|w580|nf",
         body="dualcab_ute", body_aliases="dual cab utility|dual cab pick up|ute"),
]

ALL_LANES += [
    lane("mg_hs_essence_as23", make="MG", retail_model="HS", config_model="hs", grays_model="HS",
         retail_variant=r"^Essence Auto FWD", grays_variant=r"^Essence$", year_min=2020, year_max=2024,
         anchors=[2020, 2022, 2024], badge="essence", aliases="essence", series="as23",
         engine=r"1\.5L", fuel="petrol",
         base_tag="mg_hs_essence_as23_wagon_auto_petrol",
         match_tag="mg_hs_essence_petrol_auto_wagon_as23",
         excluded="manual|diesel|hybrid|phev|awd|essence x|anfield|vibe|excite"),
    lane("mg_zs_excite_azs1", make="MG", retail_model="ZS", config_model="zs", grays_model="ZS",
         retail_variant=r"^Excite Auto 2WD", grays_variant=r"^Excite$", year_min=2019, year_max=2024,
         anchors=[2019, 2022, 2024], badge="excite", aliases="excite", series="azs1",
         engine=r"1\.5L", fuel="petrol",
         base_tag="mg_zs_excite_azs1_wagon_auto_petrol",
         match_tag="mg_zs_excite_petrol_auto_wagon_azs1",
         excluded="manual|diesel|hybrid|essence|excite plus"),
    lane("cx8_sport_kg", make="Mazda", retail_model="CX-8", config_model="cx8", grays_model="CX-8",
         retail_variant=r"^Sport KG Series Auto FWD", grays_variant=r"^Sport \(Fwd\)$",
         year_min=2020, year_max=2022, anchors=[2020, 2021, 2022], badge="sport", aliases="sport",
         series="kg", engine=r"2\.5L", fuel="petrol",
         base_tag="mazda_cx-8_sport_kg_wagon_auto_petrol",
         match_tag="mazda_cx8_sport_petrol_auto_wagon_kg",
         excluded="manual|diesel|hybrid|awd|touring|asaki|g25", min_retail=8),
    lane("cx8_touring_kg", make="Mazda", retail_model="CX-8", config_model="cx8", grays_model="CX-8",
         retail_variant=r"^Touring KG Series Auto FWD", grays_variant=r"^Touring \(Fwd\)$",
         year_min=2020, year_max=2022, anchors=[2020, 2021, 2022], badge="touring", aliases="touring",
         series="kg", engine=r"2\.5L", fuel="petrol",
         base_tag="mazda_cx-8_touring_kg_wagon_auto_petrol",
         match_tag="mazda_cx8_touring_petrol_auto_wagon_kg",
         excluded="manual|diesel|hybrid|awd|sport|asaki|g25|touring sp"),
    lane("jolion_ultra_hybrid_a01", make="GWM", retail_model="Haval Jolion", config_model="havaljolion",
         grays_model="Haval Jolion", retail_variant=r"^Ultra Hybrid Auto$", grays_variant=r"^Ultra Hybrid$",
         year_min=2022, year_max=2025, anchors=[2022, 2023, 2025], badge="ultra hybrid",
         aliases="ultra hybrid", series="a01", engine=r"1\.5L", fuel="hybrid",
         base_tag="gwm_haval-jolion_ultra-hybrid_a01_wagon_auto_hybrid",
         match_tag="gwm_havaljolion_ultra-hybrid_hybrid_auto_wagon_a01",
         excluded="manual|diesel|petrol|premium|lux", min_retail=6),
    lane("colorado_z71_rg", make="Holden", retail_model="Colorado", config_model="colorado",
         grays_model="Colorado", retail_variant=r"^Z71 RG Auto 4x4", grays_variant=r"^Z71 \(4X4\)$",
         year_min=2016, year_max=2020, anchors=[2016, 2018, 2020], badge="z71", aliases="z71",
         series="rg", engine=r"2\.8L", fuel="diesel",
         base_tag="holden_colorado_z71_rg_dualcab-auto-diesel",
         match_tag="holden_colorado_z71_diesel_auto_dualcab-ute_rg",
         excluded="manual|petrol|hybrid|4x2|2wd|ls|ltz|ls x",
         body="dualcab_ute", body_aliases="crew cab pickup|crew cab utility|dual cab utility|ute",
         grays_body=r"^Crew Cab Pickup$"),
    lane("colorado_ls_rg_4x4", make="Holden", retail_model="Colorado", config_model="colorado",
         grays_model="Colorado", retail_variant=r"^LS RG Auto 4x4", grays_variant=r"^Ls \(4X4\)$",
         year_min=2016, year_max=2020, anchors=[2016, 2018, 2020], badge="ls", aliases="ls",
         series="rg 4x4", engine=r"2\.8L", fuel="diesel",
         base_tag="holden_colorado_ls_rg_4x4_dualcab-auto-diesel",
         match_tag="holden_colorado_ls_diesel_auto_dualcab-ute_rg-4x4",
         excluded="manual|petrol|hybrid|4x2|2wd|z71|ltz|ls x|cab chassis|space cab",
         body="dualcab_ute", body_aliases="crew cab pickup|crew cab utility|dual cab utility|ute",
         grays_body=r"^Crew Cab Pickup$"),
    lane("colorado_ltz_rg_4x4", make="Holden", retail_model="Colorado", config_model="colorado",
         grays_model="Colorado", retail_variant=r"^LTZ RG Auto 4x4", grays_variant=r"^Ltz \(4X4\)$",
         year_min=2012, year_max=2020, anchors=[2012, 2016, 2020], badge="ltz", aliases="ltz",
         series="rg 4x4", engine=r"2\.8L", fuel="diesel",
         base_tag="holden_colorado_ltz_rg_4x4_dualcab-auto-diesel",
         match_tag="holden_colorado_ltz_diesel_auto_dualcab-ute_rg-4x4",
         excluded="manual|petrol|hybrid|4x2|2wd|z71|ls|cab chassis|space cab",
         body="dualcab_ute", body_aliases="crew cab pickup|crew cab utility|dual cab utility|ute",
         grays_body=r"^Crew Cab Pickup$"),
    lane("swift_gl_navigator_az", make="Suzuki", retail_model="Swift", config_model="swift", grays_model="Swift",
         retail_variant=r"^GL Navigator(?: Safety Pack)? Auto$", grays_variant=r"^Gl Navigator$",
         year_min=2017, year_max=2021, anchors=[2017, 2019, 2021], badge="gl navigator",
         aliases="gl navigator", series="az", engine=r"1\.2L", fuel="petrol",
         base_tag="suzuki_swift_gl-navigator_az_hatch_auto_petrol",
         match_tag="suzuki_swift_gl-navigator_petrol_auto_hatch_az",
         excluded="manual|diesel|hybrid|gl shadow|gl navi|glx|sport|ez",
         body="hatch", body_aliases="hatch|hatchback"),
]

HELD_KEYS = {"prado_gxl_3_120", "prado_gxl_3_150"}
LANES = [spec for spec in ALL_LANES if str(spec["key"]) not in HELD_KEYS]
LIVE_GRAYS_DEMAND_OVERRIDES = {
    # Verified from restricted_group_map.csv immediately after the provisional
    # batch retag. The raw sold variants use looser labels than the lane specs.
    "mazda2_neo_de": 17,
    "asx_ls_xb": 14,
    "qashqai_ti_j11": 9,
    "mg3_core_szp1": 7,
    "kona_active_os": 6,
    "hiace_commuter_28_h300": 25,
}


def _norm_fuel(value: object) -> str:
    text = str(value or "").lower()
    if "diesel" in text:
        return "diesel"
    if any(token in text for token in ("petrol", "unleaded", "premium")):
        return "petrol"
    if "hybrid" in text:
        return "hybrid"
    return text.strip()


def _load_evidence() -> tuple[pd.DataFrame, pd.DataFrame]:
    retail = pd.read_csv(RETAIL_PATH, low_memory=False)
    retail = retail[
        retail["seller_type"].fillna("").astype(str).str.lower().eq("private")
        & retail["variant"].notna()
    ].copy()
    retail["fuel_norm"] = retail["fuel_type"].apply(_norm_fuel)
    retail["year"] = pd.to_numeric(retail["year"], errors="coerce")
    retail["price"] = pd.to_numeric(retail["price"], errors="coerce")
    retail["odometer"] = pd.to_numeric(retail["odometer"], errors="coerce")

    grays = pd.read_csv(GRAYS_PATH, low_memory=False)
    grays["year"] = pd.to_numeric(grays["year"], errors="coerce")
    grays["fuel_norm"] = grays["fuel_type"].apply(_norm_fuel)
    if "odometer" not in grays.columns and "odometer_reading" in grays.columns:
        grays["odometer"] = pd.to_numeric(grays["odometer_reading"], errors="coerce")
    return retail, grays


def _select_retail(retail: pd.DataFrame, spec: dict[str, object]) -> pd.DataFrame:
    selected = retail[
        retail["make"].fillna("").astype(str).str.lower().eq(str(spec["make"]).lower())
        & retail["model"].fillna("").astype(str).str.lower().eq(str(spec["retail_model"]).lower())
        & retail["variant"].fillna("").astype(str).str.contains(
            str(spec["retail_variant"]), case=False, regex=True
        )
        & retail["year"].between(int(spec["year_min"]), int(spec["year_max"]), inclusive="both")
        & retail["engine"].fillna("").astype(str).str.contains(str(spec["engine"]), case=False, regex=True)
        & retail["fuel_norm"].eq(str(spec["fuel"]))
        & retail["transmission"].fillna("").astype(str).str.contains("auto", case=False)
    ].copy()
    return selected.dropna(subset=["year", "price", "odometer"]).drop_duplicates(subset=["ad_id"])


def _select_grays(grays: pd.DataFrame, spec: dict[str, object]) -> pd.DataFrame:
    selected = grays[
        grays["make"].fillna("").astype(str).str.lower().eq(str(spec["make"]).lower())
        & grays["model"].fillna("").astype(str).str.lower().eq(str(spec["grays_model"]).lower())
        & grays["variant"].fillna("").astype(str).str.contains(
            str(spec["grays_variant"]), case=False, regex=True
        )
        & grays["year"].between(int(spec["year_min"]), int(spec["year_max"]), inclusive="both")
        & grays["transmission"].fillna("").astype(str).str.contains("auto", case=False)
        & grays["fuel_norm"].eq(str(spec["fuel"]))
    ].copy()
    if str(spec["grays_body"]):
        selected = selected[
            selected["body_type"].fillna("").astype(str).str.contains(
                str(spec["grays_body"]), case=False, regex=True
            )
        ].copy()
    return selected


def _append_unique(
    path: Path,
    rows: list[dict[str, object]],
    key_columns: list[str],
    managed_values: set[str],
) -> None:
    existing = pd.read_csv(path, low_memory=False)
    existing = existing[~existing[key_columns[0]].astype(str).isin(managed_values)].copy()
    incoming = pd.DataFrame(rows, columns=existing.columns)
    combined = pd.concat([existing, incoming], ignore_index=True)
    combined = combined.drop_duplicates(subset=key_columns, keep="last")
    write_dataframe_csv_atomic(combined, path, index=False)


def main() -> int:
    retail, grays = _load_evidence()
    proposals: list[pd.DataFrame] = []
    report_rows: list[dict[str, object]] = []
    allowed_rows: list[dict[str, object]] = []
    group_rows: list[dict[str, object]] = []
    supported_rows: list[dict[str, object]] = []
    override_rows: list[dict[str, object]] = []

    for spec in LANES:
        market = _select_retail(retail, spec)
        sold = _select_grays(grays, spec)
        grays_demand = max(
            len(sold), LIVE_GRAYS_DEMAND_OVERRIDES.get(str(spec["key"]), 0)
        )
        if grays_demand < 6:
            report_rows.append(
                {
                    "lane_key": spec["key"],
                    "base_curve_tag": spec["base_tag"],
                    "match_tag": spec["match_tag"],
                    "retail_rows_raw": len(market),
                    "retail_rows_used": 0,
                    "retail_rows_trimmed": 0,
                    "grays_sold_demand": grays_demand,
                    "retail_year_min": int(market["year"].min()) if not market.empty else None,
                    "retail_year_max": int(market["year"].max()) if not market.empty else None,
                    "retail_km_min": int(market["odometer"].min()) if not market.empty else None,
                    "retail_km_max": int(market["odometer"].max()) if not market.empty else None,
                    "anchor_years": "|".join(map(str, spec["anchors"])),
                    "decision": "held_insufficient_grays_demand",
                }
            )
            continue
        if len(market) < int(spec["min_retail"]):
            raise RuntimeError(f"{spec['key']} unexpectedly has only {len(market)} clean retail rows")
        active = market.rename(
            columns={"year": "year_numeric", "price": "price_numeric", "odometer": "odometer_numeric"}
        )
        sold_for_proposal = pd.DataFrame(
            {
                "year_numeric": sold["year"],
                "price_numeric": pd.to_numeric(sold["price"], errors="coerce"),
                "odometer_numeric": pd.to_numeric(sold["odometer"], errors="coerce"),
            }
        )
        proposal, metadata = propose_curve_from_evidence(
            base_curve_tag=str(spec["base_tag"]),
            active_market_df=active,
            sold_df=sold_for_proposal,
            anchor_years=list(spec["anchors"]),
            buckets=BUCKETS,
            evidence_source="private Carsales Apify batch mR71gh69iHA8jcSVG",
        )
        if proposal.empty:
            raise RuntimeError(f"{spec['key']} produced no curve proposal")
        for column in ("price_low", "price_mid", "price_high"):
            proposal[column] = (pd.to_numeric(proposal[column]) / 100).round().astype(int) * 100
        proposals.append(proposal[list(CURVE_COLUMNS)])

        note = (
            f"Built from {metadata.active_rows_used} exact private Carsales rows "
            f"({metadata.active_rows_trimmed} price outliers trimmed) spanning "
            f"{int(market['year'].min())}-{int(market['year'].max())}; "
            f"{grays_demand} matching live Grays sold records prioritised this lane. "
            "Adjacent trims generations fuels transmissions and drivetrains remain separate."
        )
        report_rows.append(
            {
                "lane_key": spec["key"],
                "base_curve_tag": spec["base_tag"],
                "match_tag": spec["match_tag"],
                "retail_rows_raw": len(market),
                "retail_rows_used": metadata.active_rows_used,
                "retail_rows_trimmed": metadata.active_rows_trimmed,
                "grays_sold_demand": grays_demand,
                "retail_year_min": int(market["year"].min()),
                "retail_year_max": int(market["year"].max()),
                "retail_km_min": int(market["odometer"].min()),
                "retail_km_max": int(market["odometer"].max()),
                "anchor_years": "|".join(map(str, spec["anchors"])),
                "decision": "published",
            }
        )
        allowed_rows.append(
            {
                "canonical_tag": spec["match_tag"],
                "make": str(spec["make"]).lower(),
                "model": spec["config_model"],
                "body": spec["body"],
                "fuel": spec["fuel"],
                "transmission": "auto",
                "badge": spec["badge"],
                "series": spec["series"],
                "allowed_badge_aliases": spec["aliases"],
                "allowed_body_aliases": spec["body_aliases"],
                "excluded_keywords": spec["excluded"],
            }
        )
        group_rows.append(
            {
                "match_tag": spec["match_tag"],
                "base_curve_tag": spec["base_tag"],
                "status": "active",
                "notes": note,
            }
        )
        supported_rows.append(
            {
                "base_curve_tag": spec["base_tag"],
                "make": str(spec["make"]).lower(),
                "model": str(spec["retail_model"]).lower(),
                "body": spec["body"],
                "fuel": spec["fuel"],
                "transmission": "auto",
                "generation": spec["series"],
                "coverage_status": "live_now",
                "resale_supported": 1,
                "notes": note,
            }
        )
        override_rows.append(
            {
                "base_curve_tag": spec["base_tag"],
                "anchor_years": "|".join(map(str, spec["anchors"])),
                "notes": note,
            }
        )

    curves_path = ROOT / "CSV_data" / "restricted" / "curves.csv"
    existing_curves = pd.read_csv(curves_path)
    new_curves = pd.concat(proposals, ignore_index=True) if proposals else pd.DataFrame(columns=CURVE_COLUMNS)
    managed_base_tags = {str(spec["base_tag"]) for spec in ALL_LANES}
    managed_match_tags = {str(spec["match_tag"]) for spec in ALL_LANES}
    existing_curves = existing_curves[~existing_curves["canonical_tag"].astype(str).isin(managed_base_tags)]
    write_dataframe_csv_atomic(
        pd.concat([existing_curves, new_curves], ignore_index=True),
        curves_path,
        index=False,
    )
    _append_unique(
        ROOT / "config" / "allowed_variants.csv", allowed_rows, ["canonical_tag"], managed_match_tags
    )
    _append_unique(
        ROOT / "config" / "curve_groups_v2.csv", group_rows, ["match_tag"], managed_match_tags
    )
    _append_unique(
        ROOT / "config" / "supported_curve_universe_v1.csv",
        supported_rows,
        ["base_curve_tag"],
        managed_base_tags,
    )
    _append_unique(
        ROOT / "config" / "curve_anchor_overrides_v2.csv",
        override_rows,
        ["base_curve_tag"],
        managed_base_tags,
    )
    write_dataframe_csv_atomic(pd.DataFrame(report_rows), REPORT_PATH, index=False)
    rejection_ledger = pd.read_csv(REJECTION_LEDGER_PATH, low_memory=False)
    held_report = [
        row for row in report_rows if row["decision"] == "held_insufficient_grays_demand"
    ]
    assessed_keys = {str(row["lane_key"]) for row in report_rows}
    rejection_ledger = rejection_ledger[
        ~rejection_ledger["lane_key"].astype(str).isin(assessed_keys)
    ].copy()
    rejection_rows = [
        {
            "decision_date": "2026-07-29",
            "lane_key": row["lane_key"],
            "vehicle_lane": row["base_curve_tag"],
            "grays_sold_demand": row["grays_sold_demand"],
            "evidence_source": "private Carsales shared batch",
            "evidence_rows": row["retail_rows_raw"],
            "decision": "held_insufficient_live_grays_demand",
            "reason": (
                "The live Grays sold source contains fewer than six matching auction "
                "records; an earlier provisional demand signal used a non-live source."
            ),
            "reconsider_when": "At least 6 matching rows exist in live sold_cars.csv",
            "apify_run_id": "mR71gh69iHA8jcSVG",
            "apify_cost_usd": 0,
        }
        for row in held_report
    ]
    write_dataframe_csv_atomic(
        pd.concat(
            [rejection_ledger, pd.DataFrame(rejection_rows, columns=rejection_ledger.columns)],
            ignore_index=True,
        ),
        REJECTION_LEDGER_PATH,
        index=False,
    )

    published_count = sum(row["decision"] == "published" for row in report_rows)
    print(f"Published {published_count} governed lanes with {len(new_curves)} curve rows.")
    print(pd.DataFrame(report_rows)[
        ["lane_key", "retail_rows_used", "retail_rows_trimmed", "grays_sold_demand"]
    ].query("grays_sold_demand >= 6").to_string(index=False))
    print(f"Evidence report: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
