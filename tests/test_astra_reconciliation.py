import pytest
import pandas as pd

from shared.repair_ai_classifier import _build_prompt
from shared.repair_pricing import assess_repairs, repair_fragments_to_records


@pytest.mark.parametrize(
    "condition",
    [
        "sold as salvage vehicle.",
        "rattle noise observed in engine.",
        "engine turns over: no.",
        "starter motor faulty - non running vehicle.",
        "vehicle will also cut out after running for a short duration.",
        "issues evident with gearbox/driveline.",
        "Driveable: No.",
        "suspension soft, may require attention.",
        "brakes appear to squeak excessively while moving in reverse.",
        "warning light/s: tyre pressure.",
        "floor worn in placeswarning light/s: airbag.",
        "check rear right brake light warning message.",
        "key not found error.",
        "stop/start malfunction.",
        "vehicle will only run when connected to jump pack.",
        "passenger side (passenger sill panel) - tear.",
        "tow required on collection.",
    ],
)
def test_astra_high_confidence_safety_phrases_fail_closed(condition):
    assert assess_repairs(condition).hard_avoid is True


@pytest.mark.parametrize(
    ("condition", "canonical"),
    [
        ("aerial require attention.", "aerial_damage"),
        ("boot struts require attention.", "hatch_strut_damage"),
        ("driver and passenger sun visors require attention.", "sun_visor_damage"),
        ("unable to open glovebox needs attention.", "interior_compartment_latch_damage"),
        ("tailgate needs attention cannot open.", "tailgate_latch_or_tailgate_repair"),
        ("windscreen requires attention.", "windscreen_damage"),
        ("rear doorcards require attention.", "interior_trim_damage"),
        ("crack in driver tail light.", "lighting_damage"),
        ("condensed brakelight.", "lighting_condensation_damage"),
        ("headlights hazy.", "lighting_damage"),
        ("fuel door needs attention cannot open all the way.", "fuel_flap_damage"),
        ("rear bumper out of alignment.", "panel_alignment_damage"),
        ("bonnet struts dont work.", "bonnet_strut_damage"),
        ("lhr guard window smashed.", "window_damage"),
        ("holes on carpet.", "carpet_torn"),
        ("stains on centre console.", "interior_trim_damage"),
        ("sticky residue on dashboard.", "interior_trim_damage"),
        ("odour inside vehicle.", "interior_odour"),
        ("front end (driver head light) - misaligned.", "lighting_damage"),
        ("dislodge light indicator in driver side mirror.", "lighting_damage"),
        ("visible door pillars faded.", "cosmetic_surface_damage"),
        ("cracked panel on lower side skirt of driver side.", "panel_damage"),
        ("lower mould broken.", "replacement_required"),
        ("boot not opening.", "tailgate_latch_or_tailgate_repair"),
        ("tailgate struts need attention.", "hatch_strut_damage"),
        ("interior: spare key requires attention.", "key_missing"),
        ("vehicle on rim.", "tyre_replacement"),
        ("passenger side (wheels - passenger rear) - tear.", "tyre_replacement"),
    ],
)
def test_astra_high_confidence_repair_phrases_are_costed(condition, canonical):
    assessment = assess_repairs(condition)
    records = repair_fragments_to_records(assessment)
    canonicals = {
        item
        for record in records
        for item in str(record.get("canonical_defects") or "").split("|")
        if item
    }
    assert assessment.hard_avoid is False
    assert assessment.total_cost > 0
    assert canonical in canonicals


def test_bare_steering_wheel_fragment_is_ignored_without_masking_wear():
    bare = assess_repairs("steering wheel.")
    worn = assess_repairs("steering wheel worn.")

    assert [record["status"] for record in repair_fragments_to_records(bare)] == ["ignored"]
    assert bare.total_cost == 0
    assert worn.total_cost > 0


@pytest.mark.parametrize(
    "condition",
    [
        "Driveable: Yes.",
        "Sold unregistered.",
        "Vehicles Will Be Sold Unregistered To Interstate Buyers.",
        "dvd player untested.",
        "low fuel.",
        "bluetooth.",
        "tow bar.",
        "photographs.",
        "low tire pressure.",
        "1 ownerlog books includedservice records includedregistration:sold registered to all buyers.",
    ],
)
def test_astra_metadata_fragments_are_ignored(condition):
    assessment = assess_repairs(condition)
    records = repair_fragments_to_records(assessment)
    assert assessment.hard_avoid is False
    assert assessment.total_cost == 0
    assert [record["status"] for record in records] == ["ignored"]


def test_astra_prompt_carries_project_hard_avoid_policy():
    prompt = _build_prompt(
        pd.DataFrame(
            [
                {
                    "repair_key": "sold as salvage vehicle",
                    "repair_item": "sold as salvage vehicle.",
                    "status": "unclassified",
                    "category": "unclassified",
                    "example_vehicles": "Example",
                    "example_condition_notes": "sold as salvage vehicle",
                }
            ]
        )
    )

    assert "sold-as-salvage status" in prompt
    assert "tow or tilt-tray requirements" in prompt
    assert "coolant issues" in prompt
    assert "tyre-pressure warnings" in prompt
    assert "service_warning_message" in prompt


def test_concatenated_console_and_paint_fragment_keeps_both_costs():
    assessment = assess_repairs(
        "coating on console coming off and stickypaint cracked on various panels."
    )
    records = repair_fragments_to_records(assessment)
    canonicals = {
        item
        for record in records
        for item in str(record.get("canonical_defects") or "").split("|")
        if item
    }

    assert assessment.total_cost > 0
    assert {"interior_trim_damage", "paint_damage"}.issubset(canonicals)


@pytest.mark.parametrize(
    "condition",
    [
        "**Inspection Highly Recommended**.",
        "inspection advised before bidding on vehicle.",
        (
            "prospective buyers are strongly encouraged to inspect the asset prior "
            "to bidding and satisfy themselves as to its condition."
        ),
    ],
)
def test_inspection_language_keeps_unknown_condition_buffer(condition):
    assessment = assess_repairs(condition)
    assert assessment.hard_avoid is False
    assert assessment.total_cost == 300
