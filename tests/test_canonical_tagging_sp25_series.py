from shared.canonical_tagging import _extract_series_code, _normalize_series_code


def test_sp25_badge_does_not_mask_following_bl_series_code():
    assert _normalize_series_code(_extract_series_code("SP25 BL")) == "bl10f1"
