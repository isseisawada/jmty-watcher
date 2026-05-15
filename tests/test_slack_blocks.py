"""Slack Block Kit ペイロード生成の構造テスト。"""

from __future__ import annotations

import json

from watcher.models import Classification, Listing
from watcher.slack_notifier import build_listing_blocks


def _sample() -> tuple[Listing, Classification]:
    listing = Listing(
        article_id="article-1o9e6w",
        url="https://jmty.jp/okinawa/sale-oth/article-1o9e6w",
        title="【築3年・超美品】6mトレーラーハウス／民泊・サロン・事務所に最適",
        price_yen=4_000_000,
        prefecture="沖縄",
        city="うるま市",
        category_label="その他",
        thumbnail_url="https://img.cdn.jmty.jp/image/article-1o9e6w-1.jpg",
        favorite_count=42,
    )
    classification = Classification(
        is_actual_trailer_house=True,
        seller_type="individual",
        trailer_category="residential",
        estimated_market_price_yen=6_500_000,
        price_gap_ratio=0.625,
        condition_grade="A",
        priority="S",
        concerns=["写真が室内中心で外装・シャーシが確認できない", "沖縄からの輸送費要考慮"],
        sales_pitch_hook="築3年・新品780万の物件が400万は破格で、SECOND HANDでも十分再販可能",
        model_version="claude-sonnet-4-6",
    )
    return listing, classification


def test_build_listing_blocks_contains_expected_actions() -> None:
    listing, classification = _sample()
    blocks = build_listing_blocks(
        listing_id="abc-123",
        listing=listing,
        classification=classification,
        days_since_posted=4,
    )
    # JSON シリアライズ可能であること
    json.dumps(blocks)

    types = [b["type"] for b in blocks]
    assert "header" in types
    assert "section" in types
    assert "image" in types
    assert "actions" in types

    actions_block = next(b for b in blocks if b["type"] == "actions")
    action_ids = [e.get("action_id") for e in actions_block["elements"]]
    assert "view_dm" in action_ids
    assert "open_listing" in action_ids
    assert "reject" in action_ids


def test_header_priority_emoji() -> None:
    listing, classification = _sample()
    blocks = build_listing_blocks(
        listing_id="x",
        listing=listing,
        classification=classification,
        days_since_posted=None,
    )
    header_text = blocks[0]["text"]["text"]
    assert "[S]" in header_text


def test_handles_missing_optional_fields() -> None:
    listing = Listing(
        article_id="article-x",
        url="https://jmty.jp/x",
        title=None,
        price_yen=None,
        prefecture=None,
        city=None,
        category_label=None,
        thumbnail_url=None,
    )
    classification = Classification(
        is_actual_trailer_house=True,
        seller_type="unknown",
        trailer_category="unknown",
        estimated_market_price_yen=None,
        price_gap_ratio=None,
        condition_grade="C",
        priority="B",
        concerns=[],
        sales_pitch_hook="",
        model_version="x",
    )
    blocks = build_listing_blocks(
        listing_id="x",
        listing=listing,
        classification=classification,
        days_since_posted=None,
    )
    json.dumps(blocks)  # クラッシュしないこと
