from scripts.extract_grays_condition_repairs import filter_feature_only_condition_text


def test_filter_feature_only_condition_text_removes_embedded_features_tail() -> None:
    cleaned, dropped = filter_feature_only_condition_text(
        "rear bumper r medium scuff on rear bumper features:"
        "air conditioning electric windows reversing camera"
    )

    assert cleaned == "rear bumper r medium scuff on rear bumper"
    assert dropped == ["features:air conditioning electric windows reversing camera"]


def test_filter_feature_only_condition_text_drops_standalone_feature_lines() -> None:
    cleaned, dropped = filter_feature_only_condition_text(
        "reversing camera\ncracked windscreen\nmulti function steering wheel"
    )

    assert cleaned == "cracked windscreen"
    assert dropped == ["reversing camera", "multi function steering wheel"]
