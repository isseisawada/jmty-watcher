"""Slack Block Kit ペイロード生成の構造テスト。"""

from __future__ import annotations

import json

from watcher.models import Classification, Listing
from watcher.slack_notifier import SHEET_REGISTERED_BANNER, build_listing_blocks


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


def test_build_listing_blocks_first_block_is_sheet_banner() -> None:
    listing, classification = _sample()
    blocks = build_listing_blocks(
        listing_id="abc-123",
        listing=listing,
        classification=classification,
        days_since_posted=4,
        sheets_view_url="https://docs.google.com/spreadsheets/d/abc/edit",
    )
    json.dumps(blocks)
    # 先頭にスプシ追加バナーが入る
    assert blocks[0]["type"] == "section"
    assert blocks[0]["text"]["text"] == SHEET_REGISTERED_BANNER
    # 次にタイトル header
    assert blocks[1]["type"] == "header"


def test_actions_have_sheet_and_listing_buttons_only() -> None:
    listing, classification = _sample()
    blocks = build_listing_blocks(
        listing_id="abc-123",
        listing=listing,
        classification=classification,
        days_since_posted=4,
        sheets_view_url="https://docs.google.com/spreadsheets/d/abc/edit",
    )
    actions_block = next(b for b in blocks if b["type"] == "actions")
    action_ids = [e.get("action_id") for e in actions_block["elements"]]
    assert action_ids == ["open_sheet", "open_listing"]

    sheet_btn = next(e for e in actions_block["elements"] if e["action_id"] == "open_sheet")
    listing_btn = next(e for e in actions_block["elements"] if e["action_id"] == "open_listing")
    assert sheet_btn["url"] == "https://docs.google.com/spreadsheets/d/abc/edit"
    assert listing_btn["url"] == listing.url
    # DM文/スルー ボタンは廃止済み
    assert "view_dm" not in action_ids
    assert "reject" not in action_ids


def test_actions_omit_sheet_button_when_view_url_missing() -> None:
    listing, classification = _sample()
    blocks = build_listing_blocks(
        listing_id="x",
        listing=listing,
        classification=classification,
        days_since_posted=None,
        sheets_view_url=None,
    )
    actions_block = next(b for b in blocks if b["type"] == "actions")
    action_ids = [e.get("action_id") for e in actions_block["elements"]]
    assert action_ids == ["open_listing"]


def test_header_priority_emoji() -> None:
    listing, classification = _sample()
    blocks = build_listing_blocks(
        listing_id="x",
        listing=listing,
        classification=classification,
        days_since_posted=None,
    )
    # 先頭がバナー、次が header（[S] が入る）
    header_block = next(b for b in blocks if b["type"] == "header")
    assert "[S]" in header_block["text"]["text"]


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
