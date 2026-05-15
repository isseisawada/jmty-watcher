"""classifier._parse_classification の入力ゆれ耐性テスト。"""

from __future__ import annotations

from watcher.classifier import _parse_classification


def test_parse_full_valid() -> None:
    data = {
        "is_actual_trailer_house": True,
        "seller_type": "individual",
        "trailer_category": "residential",
        "estimated_market_price_yen": 6500000,
        "price_gap_ratio": 0.625,
        "condition_grade": "A",
        "priority": "S",
        "concerns": ["輸送費要考慮"],
        "sales_pitch_hook": "築3年で破格",
    }
    c = _parse_classification(data, model_version="claude-sonnet-4-6")
    assert c.priority == "S"
    assert c.seller_type == "individual"
    assert c.trailer_category == "residential"
    assert c.estimated_market_price_yen == 6500000
    assert c.price_gap_ratio == 0.625
    assert c.condition_grade == "A"
    assert c.is_actual_trailer_house is True
    assert c.concerns == ["輸送費要考慮"]


def test_parse_falls_back_for_invalid_enum() -> None:
    data = {"priority": "SS", "seller_type": "robot", "trailer_category": "spaceship",
            "condition_grade": "Z"}
    c = _parse_classification(data, model_version="x")
    assert c.priority == "C"
    assert c.seller_type == "unknown"
    assert c.trailer_category == "unknown"
    assert c.condition_grade == "C"


def test_parse_coerces_numeric_strings() -> None:
    data = {"estimated_market_price_yen": "6500000", "price_gap_ratio": "0.5"}
    c = _parse_classification(data, model_version="x")
    assert c.estimated_market_price_yen == 6500000
    assert c.price_gap_ratio == 0.5


def test_parse_handles_nulls() -> None:
    data = {"estimated_market_price_yen": None, "price_gap_ratio": None}
    c = _parse_classification(data, model_version="x")
    assert c.estimated_market_price_yen is None
    assert c.price_gap_ratio is None


def test_parse_concerns_truncated_to_10() -> None:
    data = {"concerns": [f"懸念{i}" for i in range(20)]}
    c = _parse_classification(data, model_version="x")
    assert len(c.concerns) == 10
