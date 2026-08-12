from shared.canonical_tagging import (
    _alias_in_text,
    _normalize_body,
    _normalize_series_code,
    infer_fuel_type_from_series,
)


def test_body_alias_order_preserves_people_mover_and_does_not_guess_fastback():
    assert _normalize_body("", "Kia Carnival commercial people mover") == "people_mover"
    assert _normalize_body("", "Ford Mustang Fastback GT") == ""
    assert _normalize_body("", "Ford Mustang Fastback GT Coupe") == "coupe"


def test_punctuation_alias_boundaries_match_whole_alias_only():
    assert _alias_in_text("Corolla ST (4x4) automatic", "ST (4x4)")
    assert not _alias_in_text("Corolla XST (4x4) automatic", "ST (4x4)")


def test_mercedes_ml_badges_are_ignored_without_suppressing_unknown_series():
    assert _normalize_series_code("ML250") == ""
    assert _normalize_series_code("ML350") == ""
    assert _normalize_series_code("ML999") == "ml999"


def test_hybrid_series_inference_is_centralized_and_conservative():
    assert infer_fuel_type_from_series("AXAH52R") == "Hybrid"
    assert infer_fuel_type_from_series("ZWE211R") == "Hybrid"
    assert infer_fuel_type_from_series("W166") == ""
